from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = Path(os.getenv("GIGSIM_SEED_PATH", str(ROOT / "data" / "processed" / "gigsim_seed.json")))
DB_PATH = Path(os.getenv("GIGSIM_DB_PATH", str(ROOT / "data" / "processed" / "gigsim.sqlite3")))
API_TOKEN = os.getenv("GIGSIM_API_TOKEN", "local-gigsim-token")
RATE_LIMIT_PER_MINUTE = int(os.getenv("GIGSIM_RATE_LIMIT_PER_MINUTE", "60"))
INITIAL_CONNECTS = int(os.getenv("GIGSIM_INITIAL_CONNECTS", "500"))


class ProposalSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    cover_letter: str = Field(min_length=1, max_length=5000)
    screening_answers: list[str] = Field(default_factory=list, max_length=20)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    amount: float = Field(ge=0, le=1_000_000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    approved: bool


class MessageSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    approved: bool


def _default_seed() -> dict[str, Any]:
    clients = {}
    try:
        job_items = json.loads((ROOT / "data" / "sample" / "jobs.json").read_text(encoding="utf-8"))
        history = json.loads(
            (ROOT / "data" / "sample" / "client_history.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Unable to load bundled GigSim fallback fixtures") from exc
    for index, job in enumerate(job_items):
        client_id = str(job.get("client_id") or f"synthetic-client-sample-{index + 1:03d}")
        job["client_id"] = client_id
        job.setdefault("data_provenance", "starter_kit_synthetic")
        seed_history = history[index % len(history)] if history else {}
        clients[client_id] = {
            "client_id": client_id,
            "history": seed_history,
            "hidden_preferences": {
                "must_have_skills": list(job.get("required_skills", []))[:1],
                "budget_ceiling": (job.get("budget") or {}).get("max"),
                "dislikes_generic_openings": True,
                "preferred_terms": list(job.get("required_skills", []))[:2],
            },
        }
    return {"metadata": {"dataset_type": "starter_kit_synthetic"}, "jobs": job_items, "clients": clients}


def load_seed(path: Path = SEED_PATH) -> dict[str, Any]:
    if not path.is_file():
        return _default_seed()
    try:
        seed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load GigSim seed: {path}") from exc
    if (
        not isinstance(seed, dict)
        or not isinstance(seed.get("jobs"), list)
        or not isinstance(seed.get("clients"), dict)
    ):
        raise TypeError("GigSim seed must contain jobs and clients")
    fallback = _default_seed()
    job_ids = {str(job.get("job_id")) for job in seed["jobs"]}
    client_ids = set(seed["clients"])
    for job in fallback["jobs"]:
        if str(job["job_id"]) not in job_ids:
            seed["jobs"].append(job)
    seed["clients"].update(
        {client_id: client for client_id, client in fallback["clients"].items() if client_id not in client_ids}
    )
    return seed


@contextmanager
def _connection(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _initialize_db(path: Path, initial_connects: int) -> None:
    with _connection(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                outcome TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS idempotency (
                key TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                response TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS simulator_state (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO simulator_state (key, value) VALUES ('connects_balance', ?)",
            (initial_connects,),
        )


def _auth(request: Request, authorization: str | None = Header(default=None)) -> str:
    if not API_TOKEN or not secrets.compare_digest(
        (authorization or ""), f"Bearer {API_TOKEN}"
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    user_id = request.headers.get("X-User-Id", "local-user")
    if not user_id or len(user_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid X-User-Id")
    now = time.monotonic()
    stamps = request.app.state.request_times[user_id]
    while stamps and now - stamps[0] >= 60:
        stamps.popleft()
    if len(stamps) >= request.app.state.rate_limit:
        raise HTTPException(
            status_code=429,
            detail="Simulator rate limit exceeded",
            headers={"Retry-After": "60"},
        )
    stamps.append(now)
    request.app.state.request_count += 1
    interval = request.app.state.fault_interval
    if interval > 0 and request.app.state.request_count % interval == 0:
        raise HTTPException(status_code=503, detail="Synthetic transient simulator failure")
    return user_id


def _job(request: Request, job_id: str) -> dict[str, Any]:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _client(request: Request, client_id: str) -> dict[str, Any]:
    client = request.app.state.clients.get(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _outcome(job: dict[str, Any], client: dict[str, Any], submission: ProposalSubmission) -> str:
    preferences = client["hidden_preferences"]
    text = f"{submission.cover_letter} {' '.join(submission.screening_answers)}".casefold()
    required = [str(skill).casefold() for skill in preferences.get("must_have_skills", [])]
    skill_score = sum(skill in text for skill in required) / max(1, len(required))
    title_terms = [term.casefold() for term in job["title"].split() if len(term) > 3]
    personal = any(term in text for term in title_terms)
    generic = text.lstrip().startswith(
        ("dear hiring manager", "i am excited to apply", "i am the perfect", "to whom it may concern")
    )
    ceiling = preferences.get("budget_ceiling")
    budget_ok = ceiling is None or submission.amount <= float(ceiling)
    screening_score = (
        sum(bool(answer.strip()) for answer in submission.screening_answers)
        / max(1, len(job.get("screening_questions", [])))
        if job.get("screening_questions")
        else 1.0
    )
    probability = 0.2 + 0.35 * skill_score + 0.2 * personal + 0.1 * budget_ok + 0.15 * screening_score
    if preferences.get("dislikes_generic_openings") and generic:
        probability -= 0.25
    draw = int(hashlib.sha256(submission.idempotency_key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    if draw >= probability:
        return "ignored"
    hire_probability = 0.15 + 0.5 * skill_score + 0.15 * personal + 0.1 * budget_ok
    hire_draw = int(hashlib.sha256(f"hire:{submission.idempotency_key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    if hire_draw < hire_probability:
        return "hired"
    interview_draw = int(hashlib.sha256(f"interview:{submission.idempotency_key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "interview" if interview_draw < 0.45 else "replied"


def create_app(
    *,
    db_path: Path | None = None,
    seed_data: dict[str, Any] | None = None,
    rate_limit: int = RATE_LIMIT_PER_MINUTE,
    fault_interval: int = 97,
) -> FastAPI:
    database_path = db_path or DB_PATH

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        seed = seed_data or load_seed()
        _initialize_db(database_path, INITIAL_CONNECTS)
        app.state.jobs = {str(job["job_id"]): job for job in seed["jobs"]}
        app.state.clients = seed["clients"]
        app.state.seed_metadata = seed.get("metadata", {})
        yield

    app = FastAPI(title="GigSim Local Marketplace", version="1.0.0", lifespan=lifespan)
    app.state.db_path = database_path
    app.state.request_times = defaultdict(deque)
    app.state.request_count = 0
    app.state.rate_limit = rate_limit
    app.state.fault_interval = fault_interval

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "service": "local-gigsim", "dataset_type": app.state.seed_metadata.get("dataset_type")}

    @app.get("/api/jobs")
    async def search_jobs(
        request: Request,
        query: str = "",
        limit: int = 100,
        _user: str = Depends(_auth),
    ) -> list[dict[str, Any]]:
        if len(query) > 500 or not 1 <= limit <= 500:
            raise HTTPException(status_code=422, detail="Invalid query or limit")
        terms = query.casefold().split()
        jobs = [
            job
            for job in request.app.state.jobs.values()
            if not terms
            or all(
                term in f"{job['title']} {job['description']}".casefold()
                for term in terms
            )
        ]
        return jobs[:limit]

    @app.get("/api/jobs/{job_id}")
    async def get_job(
        request: Request, job_id: str, _user: str = Depends(_auth)
    ) -> dict[str, Any]:
        return _job(request, job_id)

    @app.get("/api/clients/{client_id}/history")
    async def get_client_history(
        request: Request, client_id: str, _user: str = Depends(_auth)
    ) -> dict[str, Any]:
        client = _client(request, client_id)
        history = {key: value for key, value in client.get("history", {}).items() if key != "client_id"}
        return {"client_id": client_id, **history}

    @app.get("/api/connects")
    async def get_connects(_user: str = Depends(_auth)) -> dict[str, Any]:
        with _connection(database_path) as connection:
            balance = connection.execute(
                "SELECT value FROM simulator_state WHERE key='connects_balance'"
            ).fetchone()
        return {"balance": balance["value"], "currency": "Connects", "source": "synthetic_simulator"}

    @app.get("/api/clients/{client_id}/messages")
    async def list_messages(
        request: Request, client_id: str, _user: str = Depends(_auth)
    ) -> list[dict[str, Any]]:
        _client(request, client_id)
        with _connection(database_path) as connection:
            rows = connection.execute(
                "SELECT payload FROM messages WHERE client_id=? ORDER BY created_at",
                (client_id,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    @app.post("/api/proposals", status_code=201)
    async def submit_proposal(
        request: Request, submission: ProposalSubmission, user: str = Depends(_auth)
    ) -> dict[str, Any]:
        if not submission.approved:
            raise HTTPException(status_code=403, detail="Explicit human approval is required")
        job = _job(request, submission.job_id)
        client_id = str(job.get("client_id", ""))
        if submission.client_id != client_id:
            raise HTTPException(status_code=422, detail="Client does not match the job")
        client = _client(request, client_id)
        connects_cost = max(0, int(job.get("connects_cost", 0)))
        fingerprint = hashlib.sha256(
            submission.model_dump_json(exclude={"idempotency_key"}).encode()
        ).hexdigest()
        with _connection(database_path) as connection:
            previous = connection.execute(
                "SELECT request_hash, response FROM idempotency WHERE key=?",
                (submission.idempotency_key,),
            ).fetchone()
            if previous:
                if previous["request_hash"] != fingerprint:
                    raise HTTPException(status_code=409, detail="Idempotency key conflict")
                return json.loads(previous["response"])
            balance = connection.execute(
                "SELECT value FROM simulator_state WHERE key='connects_balance'"
            ).fetchone()["value"]
            if balance < connects_cost:
                raise HTTPException(status_code=402, detail="Insufficient simulated Connects")
            outcome = _outcome(job, client, submission)
            proposal_id = str(uuid.uuid4())
            result = {
                "proposal_id": proposal_id,
                "job_id": submission.job_id,
                "client_id": client_id,
                "status": "submitted",
                "connects_spent": connects_cost,
                "outcome": outcome,
                "outcome_provenance": "synthetic_simulator",
            }
            connection.execute(
                "INSERT INTO proposals (id, job_id, client_id, payload, outcome) VALUES (?, ?, ?, ?, ?)",
                (
                    proposal_id,
                    submission.job_id,
                    client_id,
                    submission.model_dump_json(exclude={"idempotency_key", "approved"}),
                    outcome,
                ),
            )
            if outcome in {"replied", "interview", "hired"}:
                reply_text = {
                    "replied": "Thanks for your proposal. Could you clarify the first deliverable?",
                    "interview": "Your proposal looks relevant. Could you share your availability for a short interview?",
                    "hired": "Your proposal is a strong match. I would like to discuss next steps.",
                }[outcome]
                reply = {
                    "job_id": submission.job_id,
                    "client_id": client_id,
                    "direction": "inbound",
                    "message": reply_text,
                    "provenance": "synthetic_simulator",
                }
                connection.execute(
                    "INSERT INTO messages (id, job_id, client_id, payload) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), submission.job_id, client_id, json.dumps(reply)),
                )
            connection.execute(
                "UPDATE simulator_state SET value=value-? WHERE key='connects_balance'",
                (connects_cost,),
            )
            connection.execute(
                "INSERT INTO idempotency (key, request_hash, response) VALUES (?, ?, ?)",
                (submission.idempotency_key, fingerprint, json.dumps(result)),
            )
            connection.execute(
                "INSERT INTO audit (event, entity_id, details) VALUES (?, ?, ?)",
                ("proposal_submitted", proposal_id, json.dumps({"user": user, "job_id": submission.job_id})),
            )
        return result

    @app.get("/api/proposals")
    async def list_proposals(_user: str = Depends(_auth)) -> list[dict[str, Any]]:
        with _connection(database_path) as connection:
            rows = connection.execute(
                "SELECT id, job_id, client_id, outcome, created_at FROM proposals ORDER BY created_at"
            ).fetchall()
        return [dict(row) | {"outcome_provenance": "synthetic_simulator"} for row in rows]

    @app.post("/api/messages", status_code=201)
    async def send_message(
        request: Request, submission: MessageSubmission, user: str = Depends(_auth)
    ) -> dict[str, Any]:
        if not submission.approved:
            raise HTTPException(status_code=403, detail="Explicit human approval is required")
        job = _job(request, submission.job_id)
        if submission.client_id != job.get("client_id"):
            raise HTTPException(status_code=422, detail="Client does not match the job")
        _client(request, submission.client_id)
        fingerprint = hashlib.sha256(
            submission.model_dump_json(exclude={"idempotency_key"}).encode()
        ).hexdigest()
        with _connection(database_path) as connection:
            previous = connection.execute(
                "SELECT request_hash, response FROM idempotency WHERE key=?",
                (submission.idempotency_key,),
            ).fetchone()
            if previous:
                if previous["request_hash"] != fingerprint:
                    raise HTTPException(status_code=409, detail="Idempotency key conflict")
                return json.loads(previous["response"])
            message_id = str(uuid.uuid4())
            reply_draw = int(hashlib.sha256(submission.idempotency_key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
            reply_text = (
                "Thanks for the update. Could you share a couple of suitable times?"
                if reply_draw < 0.6
                else None
            )
            result = {
                "message_id": message_id,
                "job_id": submission.job_id,
                "client_id": submission.client_id,
                "status": "sent",
                "outcome": "replied" if reply_text else "no_reply",
                "outcome_provenance": "synthetic_simulator",
                "client_reply": reply_text,
            }
            connection.execute(
                "INSERT INTO messages (id, job_id, client_id, payload) VALUES (?, ?, ?, ?)",
                (message_id, submission.job_id, submission.client_id, json.dumps(result)),
            )
            if reply_text:
                connection.execute(
                    "INSERT INTO messages (id, job_id, client_id, payload) VALUES (?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        submission.job_id,
                        submission.client_id,
                        json.dumps(
                            {
                                "job_id": submission.job_id,
                                "client_id": submission.client_id,
                                "direction": "inbound",
                                "message": reply_text,
                                "provenance": "synthetic_simulator",
                            }
                        ),
                    ),
                )
            connection.execute(
                "INSERT INTO idempotency (key, request_hash, response) VALUES (?, ?, ?)",
                (submission.idempotency_key, fingerprint, json.dumps(result)),
            )
            connection.execute(
                "INSERT INTO audit (event, entity_id, details) VALUES (?, ?, ?)",
                ("message_sent", message_id, json.dumps({"user": user, "job_id": submission.job_id})),
            )
        return result

    return app


app = create_app()
