from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.marketplace_port import create_marketplace_port
from agent.nodes.compliance import check as compliance_check
from agent.pipeline import analyze_job
from agent.sample_data import freelancers, portfolio_items
from rag.verify import remove_unsupported_claims, verify_claims

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("GIGBID_DB_PATH", str(ROOT / "data" / "processed" / "gigbid.sqlite3")))
API_TOKEN = os.getenv("GIGBID_API_TOKEN", "local-dev-token")
_graph_connection: sqlite3.Connection | None = None
_bid_graph = None
_conversation_graph = None
_approval_lock = asyncio.Lock()


class EditProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cover_letter: str = Field(min_length=1, max_length=5000)
    screening_answers: list[str] = Field(default_factory=list, max_length=20)


class RejectProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


class MessageDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=3000)
    persona_id: str = Field(default="sample-ai-engineer", min_length=1, max_length=128)


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS idempotency (
                tenant_id TEXT NOT NULL,
                key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response TEXT NOT NULL,
                PRIMARY KEY (tenant_id, key)
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                event TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(idempotency)").fetchall()}
        if "request_hash" not in columns:
            conn.execute("ALTER TABLE idempotency ADD COLUMN request_hash TEXT NOT NULL DEFAULT ''")


def current_tenant(authorization: str | None = Header(default=None)) -> str:
    if not API_TOKEN or not secrets.compare_digest((authorization or ""), f"Bearer {API_TOKEN}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    return "local-user"


async def _marketplace_job(job_id: str) -> dict[str, Any]:
    port = create_marketplace_port()
    try:
        job = await port.get_job(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Marketplace service is unavailable") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail="Marketplace service rejected the job lookup"
        ) from exc
    if job.get("job_id") != job_id:
        raise HTTPException(status_code=502, detail="Marketplace returned a mismatched job")
    return job


async def _marketplace_jobs() -> list[dict[str, Any]]:
    port = create_marketplace_port()
    try:
        return await port.search_jobs()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Marketplace service is unavailable") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail="Marketplace service rejected the job search"
        ) from exc


async def _simulator_write(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not os.getenv("GIGSIM_BASE_URL", "").strip():
        return None
    if os.getenv("GIGBID_MARKETPLACE_MODE", "gigsim").casefold() != "gigsim":
        raise HTTPException(status_code=503, detail="Live marketplace writes are not enabled")
    port = create_marketplace_port()
    try:
        if path == "/api/proposals":
            result = await port.submit_proposal(
                payload, payload["idempotency_key"], approved=True
            )
        elif path == "/api/messages":
            result = await port.send_message(payload, payload["idempotency_key"], approved=True)
        else:
            raise ValueError(f"Unsupported simulator write path: {path}")
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503, detail="Local GigSim is unavailable; retry the same approval"
        ) from exc
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            detail = str(body.get("detail", "Local GigSim rejected the approved action"))
        except ValueError:
            detail = "Local GigSim rejected the approved action"
        raise HTTPException(
            status_code=502 if exc.response.status_code >= 500 else exc.response.status_code,
            detail=detail,
        ) from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="Marketplace adapter returned an invalid response")
    return result


def _proposal(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload"])
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        **payload,
    }


def _message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        **json.loads(row["payload"]),
    }


def _get_proposal(proposal_id: str, tenant: str) -> sqlite3.Row:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM proposals WHERE id = ? AND tenant_id = ?",
            (proposal_id, tenant),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return row


def _resume_approval(thread_id: str, *, approved: bool) -> None:
    if _bid_graph is None:
        raise HTTPException(status_code=503, detail="Approval graph is unavailable")
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = _bid_graph.get_state(config)
    desired = "approved" if approved else "rejected"
    if snapshot.values.get("approval_status") == desired:
        return
    if "approval" not in snapshot.next:
        raise HTTPException(status_code=409, detail="Graph is not waiting at the approval gate")
    _bid_graph.invoke(Command(resume={"approved": approved}), config)


def _resume_conversation(thread_id: str, *, approved: bool) -> None:
    if _conversation_graph is None:
        raise HTTPException(status_code=503, detail="Conversation graph is unavailable")
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = _conversation_graph.get_state(config)
    desired = "approved" if approved else "rejected"
    if snapshot.values.get("approval_status") == desired:
        return
    if "approval" not in snapshot.next:
        raise HTTPException(status_code=409, detail="Conversation is not waiting at approval")
    _conversation_graph.invoke(Command(resume={"approved": approved}), config)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _graph_connection, _bid_graph, _conversation_graph
    initialize_db()
    _graph_connection = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    saver = SqliteSaver(_graph_connection)
    saver.setup()
    _bid_graph = build_bid_graph(saver)
    _conversation_graph = build_conversation_graph(saver)
    yield
    _graph_connection.close()
    _graph_connection = None
    _bid_graph = None
    _conversation_graph = None


app = FastAPI(title="GigBid API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("GIGBID_CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    try:
        with connection() as conn:
            conn.execute("SELECT 1")
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="Persistence store unavailable") from exc
    return {"status": "ok", "service": "gigbid-api"}


@app.get("/api/jobs")
async def list_jobs(
    persona_id: str | None = None,
    tenant: str = Depends(current_tenant),
) -> list[dict[str, Any]]:
    del tenant
    if persona_id and persona_id not in {profile["freelancer_id"] for profile in freelancers()}:
        raise HTTPException(status_code=404, detail="Persona not found")
    results = []
    for job in await _marketplace_jobs():
        analysis = analyze_job(job, persona_id)
        results.append(
            {
                **job,
                "recommendation": analysis["decision"]["action"],
                "fit_score": analysis["fit_report"]["score"],
                "risk_score": analysis["risk_report"]["score"],
                "suggested_price_usd": analysis["price_quote"]["amount"],
            }
        )
    return results


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, tenant: str = Depends(current_tenant)) -> dict[str, Any]:
    del tenant
    return await _marketplace_job(job_id)


@app.get("/api/portfolio")
async def get_portfolio(
    persona_id: str | None = None,
    tenant: str = Depends(current_tenant),
) -> dict[str, Any]:
    del tenant
    profiles = freelancers()
    if persona_id:
        profiles = [profile for profile in profiles if profile["freelancer_id"] == persona_id]
        if not profiles:
            raise HTTPException(status_code=404, detail="Persona not found")
    selected_ids = {profile["freelancer_id"] for profile in profiles}
    return {
        "profiles": profiles,
        "evidence": [
            item for item in portfolio_items() if item.get("freelancer_id") in selected_ids
        ],
        "provenance": "synthetic_personas_and_portfolio_examples",
        "uploads_enabled": False,
    }


@app.post("/api/jobs/{job_id}/analyze", status_code=201)
async def analyze(
    job_id: str,
    persona_id: str | None = None,
    tenant: str = Depends(current_tenant),
) -> dict[str, Any]:
    job = await _marketplace_job(job_id)
    if persona_id and persona_id not in {profile["freelancer_id"] for profile in freelancers()}:
        raise HTTPException(status_code=404, detail="Persona not found")
    with connection() as conn:
        existing = conn.execute(
            "SELECT * FROM proposals WHERE tenant_id=? AND job_id=? "
            "AND status IN ('awaiting_review', 'edited') ORDER BY created_at DESC LIMIT 1",
            (tenant, job_id),
        ).fetchone()
    if existing is not None:
        return _proposal(existing)
    if _bid_graph is None:
        raise HTTPException(status_code=503, detail="Bid graph is not initialized")
    thread_id = str(uuid.uuid4())
    graph_state = _bid_graph.invoke(
        {"job": job, "persona_id": persona_id},
        {"configurable": {"thread_id": thread_id}},
    )
    result = analyze_job(job, persona_id)
    for field in (
        "job_spec",
        "risk_report",
        "fit_report",
        "decision",
        "price_quote",
        "evidence",
        "claim_verification",
        "proposal_draft",
        "critique",
        "compliance_verdict",
    ):
        if field in graph_state:
            result[field] = graph_state[field]
    result["trace_id"] = thread_id
    proposal_id = str(uuid.uuid4())
    proposal_status = (
        "awaiting_review" if result["decision"]["action"] == "bid" else "not_recommended"
    )
    payload = {
        "analysis": result,
        "proposal": result["proposal_draft"],
        "graph_thread_id": thread_id,
    }
    with connection() as conn:
        conn.execute(
            "INSERT INTO proposals (id, tenant_id, job_id, status, payload) VALUES (?, ?, ?, ?, ?)",
            (proposal_id, tenant, job_id, proposal_status, json.dumps(payload)),
        )
        conn.execute(
            "INSERT INTO audit (tenant_id, event, trace_id, details) VALUES (?, ?, ?, ?)",
            (tenant, "job_analyzed", result["trace_id"], json.dumps({"job_id": job_id})),
        )
    return {"id": proposal_id, "job_id": job_id, "status": proposal_status, **payload}


@app.get("/api/proposals")
async def list_proposals(tenant: str = Depends(current_tenant)) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 100",
            (tenant,),
        ).fetchall()
    return [_proposal(row) for row in rows]


@app.get("/api/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, tenant: str = Depends(current_tenant)) -> dict[str, Any]:
    return _proposal(_get_proposal(proposal_id, tenant))


@app.get("/api/runs")
async def list_runs(tenant: str = Depends(current_tenant)) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT event, trace_id, details, created_at FROM audit "
            "WHERE tenant_id=? ORDER BY id DESC LIMIT 100",
            (tenant,),
        ).fetchall()
    return [
        {
            "event": row["event"],
            "trace_id": row["trace_id"],
            "details": json.loads(row["details"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.get("/api/analytics")
async def get_analytics(tenant: str = Depends(current_tenant)) -> dict[str, Any]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT status, payload FROM proposals WHERE tenant_id=?", (tenant,)
        ).fetchall()
    proposals = [json.loads(row["payload"]) for row in rows]
    outcomes = [
        proposal["simulator_result"]["outcome"]
        for proposal in proposals
        if proposal.get("simulator_result", {}).get("outcome")
    ]
    replied = sum(outcome in {"replied", "interview", "hired"} for outcome in outcomes)
    hired = sum(outcome == "hired" for outcome in outcomes)
    return {
        "proposal_count": len(rows),
        "simulated_outcome_count": len(outcomes),
        "simulated_reply_rate": replied / len(outcomes) if outcomes else None,
        "simulated_hire_rate": hired / len(outcomes) if outcomes else None,
        "synthetic_connects_spent": sum(
            int(proposal.get("analysis", {}).get("price_quote", {}).get("connects_cost", 0))
            for proposal in proposals
            if proposal.get("simulator_result")
        ),
        "outcome_provenance": "synthetic_simulator",
    }


@app.get("/api/messages")
async def list_message_drafts(tenant: str = Depends(current_tenant)) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE tenant_id=? ORDER BY created_at DESC LIMIT 100",
            (tenant,),
        ).fetchall()
    return [_message(row) for row in rows]


@app.put("/api/proposals/{proposal_id}")
async def edit_proposal(
    proposal_id: str,
    request: EditProposalRequest,
    tenant: str = Depends(current_tenant),
) -> dict[str, Any]:
    row = _get_proposal(proposal_id, tenant)
    if row["status"] not in {"awaiting_review", "edited"}:
        raise HTTPException(status_code=409, detail="Only pending proposals can be edited")
    payload = json.loads(row["payload"])
    evidence = payload["analysis"]["evidence"]
    checks = verify_claims(request.cover_letter, evidence)
    filtered, supported = remove_unsupported_claims(request.cover_letter, checks)
    if filtered != request.cover_letter.strip() or not supported:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Every proposal sentence must be supported by portfolio evidence",
                "checks": checks,
            },
        )
    evidence_ids = sorted(
        {evidence_id for check in supported for evidence_id in check["evidence_ids"]}
    )
    compliance = compliance_check(filtered, evidence_ids)
    if not compliance.allowed:
        raise HTTPException(
            status_code=422,
            detail={"message": "Draft failed compliance", "violations": compliance.violations},
        )
    payload["proposal"]["cover_letter"] = filtered
    payload["proposal"]["screening_answers"] = request.screening_answers
    payload["proposal"]["evidence_ids"] = evidence_ids
    payload["analysis"]["claim_verification"] = checks
    if _bid_graph is not None and payload.get("graph_thread_id"):
        _bid_graph.update_state(
            {"configurable": {"thread_id": payload["graph_thread_id"]}},
            {"proposal_draft": payload["proposal"]},
        )
    with connection() as conn:
        conn.execute(
            "UPDATE proposals SET status='edited', payload=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND tenant_id=?",
            (json.dumps(payload), proposal_id, tenant),
        )
    return _proposal(_get_proposal(proposal_id, tenant))


@app.post("/api/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    tenant: str = Depends(current_tenant),
) -> dict[str, Any]:
    request_hash = hashlib.sha256(proposal_id.encode()).hexdigest()
    async with _approval_lock:
        with connection() as conn:
            prior = conn.execute(
                "SELECT request_hash, response FROM idempotency WHERE tenant_id=? AND key=?",
                (tenant, idempotency_key),
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key was already used for another request",
                    )
                response.headers["Idempotent-Replay"] = "true"
                return json.loads(prior["response"])
            row = conn.execute(
                "SELECT * FROM proposals WHERE id=? AND tenant_id=?",
                (proposal_id, tenant),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if row["status"] not in {"awaiting_review", "edited", "approving"}:
            raise HTTPException(status_code=409, detail=f"Proposal is {row['status']}")
        payload = json.loads(row["payload"])
        analysis = payload["analysis"]
        if analysis["decision"]["action"] != "bid" or not analysis["compliance_verdict"]["allowed"]:
            raise HTTPException(status_code=409, detail="Proposal is not eligible for approval")
        if _bid_graph is None or not payload.get("graph_thread_id"):
            raise HTTPException(status_code=503, detail="Approval graph checkpoint is unavailable")
        with connection() as conn:
            conn.execute(
                "UPDATE proposals SET status='approving', updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND tenant_id=?",
                (proposal_id, tenant),
            )
        _bid_graph.update_state(
            {"configurable": {"thread_id": payload["graph_thread_id"]}},
            {"proposal_draft": payload["proposal"]},
        )
        _resume_approval(payload["graph_thread_id"], approved=True)
        payload["proposal"]["status"] = "approved"
        job = await _marketplace_job(row["job_id"])
        simulation = await _simulator_write(
            "/api/proposals",
            {
                "job_id": row["job_id"],
                "client_id": job["client_id"],
                "cover_letter": payload["proposal"]["cover_letter"],
                "screening_answers": payload["proposal"].get("screening_answers", []),
                "evidence_ids": payload["proposal"].get("evidence_ids", []),
                "amount": analysis["price_quote"]["amount"],
                "idempotency_key": "proposal-" + hashlib.sha256(proposal_id.encode()).hexdigest(),
                "approved": True,
            },
        )
        if simulation is None:
            payload["external_submission"] = "disabled; no marketplace write was made"
        else:
            payload["simulator_result"] = simulation
            payload["external_submission"] = (
                "submitted to local GigSim; synthetic outcome: "
                f"{simulation['outcome']}"
            )
        result = {
            "id": proposal_id,
            "job_id": row["job_id"],
            "status": "approved",
            "external_submission": payload["external_submission"],
        }
        if simulation is not None:
            result["simulator_result"] = simulation
        with connection() as conn:
            conn.execute(
                "UPDATE proposals SET status='approved', payload=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND tenant_id=?",
                (json.dumps(payload), proposal_id, tenant),
            )
            conn.execute(
                "INSERT INTO audit (tenant_id, event, trace_id, details) VALUES (?, ?, ?, ?)",
                (
                    tenant,
                    "proposal_approved_no_external_write",
                    analysis["trace_id"],
                    json.dumps({"proposal_id": proposal_id}),
                ),
            )
            conn.execute(
                "INSERT INTO idempotency (tenant_id, key, request_hash, response) VALUES (?, ?, ?, ?)",
                (tenant, idempotency_key, request_hash, json.dumps(result)),
            )
    return result


@app.post("/api/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    request: RejectProposalRequest,
    tenant: str = Depends(current_tenant),
) -> dict[str, str]:
    row = _get_proposal(proposal_id, tenant)
    if row["status"] not in {"awaiting_review", "edited"}:
        raise HTTPException(status_code=409, detail=f"Proposal is {row['status']}")
    payload = json.loads(row["payload"])
    if _bid_graph is None or not payload.get("graph_thread_id"):
        raise HTTPException(status_code=503, detail="Approval graph checkpoint is unavailable")
    _resume_approval(payload["graph_thread_id"], approved=False)
    payload["rejection_reason"] = request.reason.strip()
    with connection() as conn:
        conn.execute(
            "UPDATE proposals SET status='rejected', payload=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND tenant_id=?",
            (json.dumps(payload), proposal_id, tenant),
        )
    return {"id": proposal_id, "status": "rejected"}


@app.post("/api/messages/draft", status_code=201)
async def draft_message(
    request: MessageDraftRequest, tenant: str = Depends(current_tenant)
) -> dict[str, Any]:
    job = await _marketplace_job(request.job_id)
    profile = next(
        (item for item in freelancers() if item["freelancer_id"] == request.persona_id),
        None,
    )
    if profile is None:
        raise HTTPException(status_code=422, detail="Unknown freelancer persona")
    if _conversation_graph is None:
        raise HTTPException(status_code=503, detail="Conversation graph is not initialized")
    thread_id = str(uuid.uuid4())
    state = _conversation_graph.invoke(
        {"message": request.message, "job": job, "profile": profile},
        {"configurable": {"thread_id": thread_id}},
    )
    message_id = str(uuid.uuid4())
    message_status = "awaiting_review" if state.get("status") == "pending_review" else "blocked"
    payload = {
        "intent": state.get("intent"),
        "incoming_message": request.message,
        "draft": state.get("draft", ""),
        "negotiation_decision": state.get("negotiation_decision"),
        "graph_thread_id": thread_id,
        "external_send_enabled": False,
    }
    with connection() as conn:
        conn.execute(
            "INSERT INTO messages (id, tenant_id, job_id, status, payload) VALUES (?, ?, ?, ?, ?)",
            (message_id, tenant, request.job_id, message_status, json.dumps(payload)),
        )
        conn.execute(
            "INSERT INTO audit (tenant_id, event, trace_id, details) VALUES (?, ?, ?, ?)",
            (tenant, "message_drafted", thread_id, json.dumps({"message_id": message_id})),
        )
    return {"id": message_id, "job_id": request.job_id, "status": message_status, **payload}


@app.post("/api/messages/{message_id}/reject")
async def reject_message(
    message_id: str,
    request: RejectProposalRequest,
    tenant: str = Depends(current_tenant),
) -> dict[str, str]:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE id=? AND tenant_id=?", (message_id, tenant)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Message draft not found")
    if row["status"] != "awaiting_review":
        raise HTTPException(status_code=409, detail=f"Message draft is {row['status']}")
    payload = json.loads(row["payload"])
    _resume_conversation(payload["graph_thread_id"], approved=False)
    payload["rejection_reason"] = request.reason.strip()
    with connection() as conn:
        conn.execute(
            "UPDATE messages SET status='rejected', payload=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND tenant_id=?",
            (json.dumps(payload), message_id, tenant),
        )
        conn.execute(
            "INSERT INTO audit (tenant_id, event, trace_id, details) VALUES (?, ?, ?, ?)",
            (
                tenant,
                "message_rejected",
                payload["graph_thread_id"],
                json.dumps({"message_id": message_id}),
            ),
        )
    return {"id": message_id, "status": "rejected"}


@app.post("/api/messages/{message_id}/approve")
async def approve_message(
    message_id: str,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    tenant: str = Depends(current_tenant),
) -> dict[str, Any]:
    request_hash = hashlib.sha256(f"message:{message_id}".encode()).hexdigest()
    async with _approval_lock:
        with connection() as conn:
            prior = conn.execute(
                "SELECT request_hash, response FROM idempotency WHERE tenant_id=? AND key=?",
                (tenant, idempotency_key),
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key was already used for another request",
                    )
                response.headers["Idempotent-Replay"] = "true"
                return json.loads(prior["response"])
            row = conn.execute(
                "SELECT * FROM messages WHERE id=? AND tenant_id=?",
                (message_id, tenant),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Message draft not found")
        if row["status"] != "awaiting_review":
            raise HTTPException(status_code=409, detail=f"Message draft is {row['status']}")
        payload = json.loads(row["payload"])
        _resume_conversation(payload["graph_thread_id"], approved=True)
        job = await _marketplace_job(row["job_id"])
        simulation = await _simulator_write(
            "/api/messages",
            {
                "job_id": row["job_id"],
                "client_id": job["client_id"],
                "message": payload["draft"],
                "idempotency_key": "message-" + hashlib.sha256(message_id.encode()).hexdigest(),
                "approved": True,
            },
        )
        result = {
            "id": message_id,
            "status": "approved",
            "external_send": (
                "disabled; no message was sent"
                if simulation is None
                else "sent to local GigSim; outcome is simulated"
            ),
        }
        if simulation is not None:
            result["simulator_result"] = simulation
        with connection() as conn:
            conn.execute(
                "UPDATE messages SET status='approved', updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND tenant_id=?",
                (message_id, tenant),
            )
            conn.execute(
                "INSERT INTO idempotency (tenant_id, key, request_hash, response) VALUES (?, ?, ?, ?)",
                (tenant, idempotency_key, request_hash, json.dumps(result)),
            )
            conn.execute(
                "INSERT INTO audit (tenant_id, event, trace_id, details) VALUES (?, ?, ?, ?)",
                (
                    tenant,
                    "message_approved_no_external_send",
                    payload["graph_thread_id"],
                    json.dumps({"message_id": message_id}),
                ),
            )
    return result
