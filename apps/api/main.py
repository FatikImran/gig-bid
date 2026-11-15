from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.live_proposal import (
    PORTFOLIO_PATH,
    build_owner_draft,
    load_resume_evidence,
    preview_summary,
)
from agent.marketplace_port import create_marketplace_port
from agent.model_runtime import GroqInferenceError, ModelInferenceError
from agent.nodes.compliance import check as compliance_check
from agent.pipeline import analyze_job
from agent.sample_data import freelancers, portfolio_items
from agent.upwork_marketplace import UpworkMarketplaceError
from rag.verify import verify_claims

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
    screening_answers: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    ] = Field(default_factory=list, max_length=20)


class RejectProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


class MessageDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=3000)
    persona_id: str = Field(default="sample-ai-engineer", min_length=1, max_length=128)


class OwnerOfferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(min_length=1, max_length=128)
    amount: float = Field(gt=0, allow_inf_nan=False)
    unit: Literal["hourly", "fixed"]


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
    try:
        job = await create_marketplace_port().get_job(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Marketplace service is unavailable") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail="Marketplace service rejected the job lookup"
        ) from exc
    except UpworkMarketplaceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if job.get("job_id") != job_id:
        raise HTTPException(status_code=502, detail="Marketplace returned a mismatched job")
    return job


async def _marketplace_jobs(query: str = "") -> list[dict[str, Any]]:
    try:
        port = create_marketplace_port()
        return await port.search_jobs(query) if query else await port.search_jobs()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Marketplace service is unavailable") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail="Marketplace service rejected the job search"
        ) from exc
    except UpworkMarketplaceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _live_mode() -> bool:
    return os.getenv("GIGBID_MARKETPLACE_MODE", "gigsim").casefold() == "upwork"


async def _simulator_write(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not os.getenv("GIGSIM_BASE_URL", "").strip():
        return None
    if os.getenv("GIGBID_MARKETPLACE_MODE", "gigsim").casefold() != "gigsim":
        raise HTTPException(status_code=503, detail="Live marketplace writes are not enabled")
    port = create_marketplace_port()
    try:
        if path == "/api/proposals":
            result = await port.submit_proposal(payload, payload["idempotency_key"], approved=True)
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
        raise HTTPException(
            status_code=502, detail="Marketplace adapter returned an invalid response"
        )
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


@app.exception_handler(ModelInferenceError)
async def inference_error(_request, exc: ModelInferenceError) -> JSONResponse:
    logging.getLogger("uvicorn.error").warning("Proposal inference failed: %s", exc)
    rate_limited = isinstance(exc, GroqInferenceError) and exc.status_code == 429
    return JSONResponse(
        status_code=503 if rate_limited else 502,
        content={"detail": str(exc)},
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
    query: Annotated[str, Query(max_length=160)] = "",
    tenant: str = Depends(current_tenant),
) -> list[dict[str, Any]]:
    del tenant
    if (
        not _live_mode()
        and persona_id
        and persona_id not in {profile["freelancer_id"] for profile in freelancers()}
    ):
        raise HTTPException(status_code=404, detail="Persona not found")
    results = []
    for job in await _marketplace_jobs(query.strip()):
        if job.get("data_provenance") == "upwork_live":
            results.append({**job, "recommendation": "watch", "fit_score": None})
            continue
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
    if _live_mode():
        try:
            evidence = (
                load_resume_evidence(PORTFOLIO_PATH).values() if PORTFOLIO_PATH.is_file() else []
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "profiles": [],
            "evidence": [record.model_dump() for record in evidence],
            "provenance": "local_owner_portfolio",
            "uploads_enabled": False,
        }
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
    owner_offer: OwnerOfferRequest | None = None,
    tenant: str = Depends(current_tenant),
) -> dict[str, Any]:
    live = _live_mode()
    if live and owner_offer is None:
        raise HTTPException(
            status_code=409, detail="Choose local portfolio evidence and enter your bid."
        )
    if not live and owner_offer is not None:
        raise HTTPException(status_code=409, detail="Owner offers are available in Upwork mode.")
    if (
        not live
        and persona_id
        and persona_id not in {profile["freelancer_id"] for profile in freelancers()}
    ):
        raise HTTPException(status_code=404, detail="Persona not found")
    job = await _marketplace_job(job_id)
    with connection() as conn:
        existing = conn.execute(
            "SELECT * FROM proposals WHERE tenant_id=? AND job_id=? "
            "AND COALESCE(json_extract(payload, '$.marketplace'),'gigsim')=? "
            "AND status IN ('awaiting_review', 'edited') ORDER BY created_at DESC LIMIT 1",
            (tenant, job_id, "upwork" if live else "gigsim"),
        ).fetchone()
    if existing is not None:
        result = _proposal(existing)
        if owner_offer is not None and result.get("owner_offer") != owner_offer.model_dump():
            raise HTTPException(
                status_code=409,
                detail="Review or reject the existing draft before changing its bid or evidence.",
            )
        return result
    if _bid_graph is None:
        raise HTTPException(status_code=503, detail="Bid graph is not initialized")
    thread_id = str(uuid.uuid4())
    graph_config = {"configurable": {"thread_id": thread_id}}
    if owner_offer is not None:
        try:
            evidence = load_resume_evidence(PORTFOLIO_PATH).get(owner_offer.evidence_id)
            if evidence is None:
                raise ValueError("The selected local portfolio evidence was not found.")
            graph_state = build_owner_draft(
                _bid_graph, job, evidence, owner_offer.amount, owner_offer.unit, graph_config
            )
        except (ValueError, UpworkMarketplaceError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = {
            "dry_run": {
                "connects_cost": graph_state["price_quote"]["connects_cost"],
                "external_write_enabled": False,
            }
        }
    else:
        graph_state = _bid_graph.invoke({"job": job, "persona_id": persona_id}, graph_config)
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
        "awaiting_review"
        if "approval" in _bid_graph.get_state(graph_config).next
        else "not_recommended"
    )
    payload = {
        "analysis": result,
        "proposal": result["proposal_draft"],
        "graph_thread_id": thread_id,
    }
    if owner_offer is not None:
        payload.update(
            marketplace="upwork",
            owner_offer=owner_offer.model_dump(),
            upwork_reference=job["upwork_reference"],
            upwork_url=job.get("upwork_url"),
        )
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


def _validate_proposal_content(
    cover_letter: str, screening_answers: list[str], evidence: list[dict[str, Any]]
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    sections = [("cover_letter", cover_letter)]
    sections.extend(
        (f"screening_answers[{index}]", answer) for index, answer in enumerate(screening_answers)
    )
    checks = []
    for field, text in sections:
        section_checks = verify_claims(text, evidence)
        if not section_checks or any(
            check["status"] != "supported" or not check["evidence_ids"] for check in section_checks
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Every proposal sentence must be supported by portfolio evidence",
                    "field": field,
                    "checks": section_checks,
                },
            )
        checks.extend(section_checks)

    evidence_ids = sorted(
        {evidence_id for check in checks for evidence_id in check["evidence_ids"]}
    )
    compliance = compliance_check("\n\n".join(text for _, text in sections), evidence_ids)
    if not compliance.allowed:
        raise HTTPException(
            status_code=422,
            detail={"message": "Draft failed compliance", "violations": compliance.violations},
        )
    return evidence_ids, checks, compliance.model_dump()


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
    evidence_ids, checks, compliance = _validate_proposal_content(
        request.cover_letter, request.screening_answers, payload["analysis"]["evidence"]
    )
    payload["proposal"]["cover_letter"] = request.cover_letter.strip()
    payload["proposal"]["screening_answers"] = request.screening_answers
    payload["proposal"]["evidence_ids"] = evidence_ids
    payload["analysis"]["claim_verification"] = checks
    payload["analysis"]["compliance_verdict"] = compliance
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
        live = payload.get("marketplace") == "upwork"
        if live != _live_mode():
            raise HTTPException(
                status_code=409, detail="Open this draft in its original marketplace mode."
            )
        if live and payload["proposal"].get("screening_answers"):
            raise HTTPException(
                status_code=422,
                detail="This preview supports cover letters without screening answers.",
            )
        analysis = payload["analysis"]
        if analysis["decision"]["action"] != "bid" or not analysis["compliance_verdict"]["allowed"]:
            raise HTTPException(status_code=409, detail="Proposal is not eligible for approval")
        if _bid_graph is None or not payload.get("graph_thread_id"):
            raise HTTPException(status_code=503, detail="Approval graph checkpoint is unavailable")
        proposal = payload["proposal"]
        evidence_ids, checks, compliance = _validate_proposal_content(
            proposal["cover_letter"], proposal.get("screening_answers", []), analysis["evidence"]
        )
        proposal["evidence_ids"] = evidence_ids
        analysis["claim_verification"] = checks
        analysis["compliance_verdict"] = compliance
        with connection() as conn:
            claimed = conn.execute(
                "UPDATE proposals SET status=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND tenant_id=? AND status=?",
                ("preview_requested" if live else "approving", proposal_id, tenant, row["status"]),
            )
            if claimed.rowcount != 1:
                raise HTTPException(
                    status_code=409, detail="The proposal changed. Refresh and review it again."
                )
        _bid_graph.update_state(
            {"configurable": {"thread_id": payload["graph_thread_id"]}},
            {"proposal_draft": payload["proposal"]},
        )
        _resume_approval(payload["graph_thread_id"], approved=True)
        payload["proposal"]["status"] = "approved"
        operation_key = "proposal-" + request_hash
        simulation = None
        next_status = "approved"
        event = "proposal_approved_no_external_write"
        if live:
            try:
                upstream = await create_marketplace_port().create_proposal_draft(
                    {
                        "job_reference": payload["upwork_reference"],
                        "cover_letter": proposal["cover_letter"],
                        "charged_amount": analysis["price_quote"]["amount"],
                    },
                    operation_key,
                    approved=True,
                    dry_run=False,
                )
            except UpworkMarketplaceError as exc:
                with connection() as conn:
                    conn.execute(
                        "UPDATE proposals SET status='preview_failed', updated_at=CURRENT_TIMESTAMP "
                        "WHERE id=? AND tenant_id=?",
                        (proposal_id, tenant),
                    )
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            payload["upwork_preview"] = preview_summary(upstream)
            next_status = (
                "preview_ready" if payload["upwork_preview"]["ready"] else "preview_needs_details"
            )
            event = f"upwork_proposal_{next_status}"
            payload["external_submission"] = (
                "Upwork returned a preview. No proposal was submitted."
                if payload["upwork_preview"]["ready"]
                else "Upwork returned no confirmation-ready preview. Review the listing on Upwork."
            )
        else:
            job = await _marketplace_job(row["job_id"])
            simulation = await _simulator_write(
                "/api/proposals",
                {
                    "job_id": row["job_id"],
                    "client_id": job["client_id"],
                    "cover_letter": proposal["cover_letter"],
                    "screening_answers": proposal.get("screening_answers", []),
                    "evidence_ids": proposal.get("evidence_ids", []),
                    "amount": analysis["price_quote"]["amount"],
                    "idempotency_key": operation_key,
                    "approved": True,
                },
            )
            if simulation is None:
                payload["external_submission"] = "disabled; no marketplace write was made"
            else:
                payload["simulator_result"] = simulation
                payload["external_submission"] = (
                    f"submitted to local GigSim; synthetic outcome: {simulation['outcome']}"
                )
        result = {
            "id": proposal_id,
            "job_id": row["job_id"],
            "status": next_status,
            "external_submission": payload["external_submission"],
        }
        if simulation is not None:
            result["simulator_result"] = simulation
        if live:
            result["upwork_preview"] = payload["upwork_preview"]
        with connection() as conn:
            conn.execute(
                "UPDATE proposals SET status=?, payload=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND tenant_id=?",
                (next_status, json.dumps(payload), proposal_id, tenant),
            )
            conn.execute(
                "INSERT INTO audit (tenant_id, event, trace_id, details) VALUES (?, ?, ?, ?)",
                (
                    tenant,
                    event,
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
    live = _live_mode()
    job = {}
    profile = None
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="Enter the received message.")
    if not live:
        if not request.job_id:
            raise HTTPException(status_code=422, detail="Choose a related simulator job.")
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
    if live:
        payload["marketplace"] = "upwork"
    job_id = request.job_id or ""
    with connection() as conn:
        conn.execute(
            "INSERT INTO messages (id, tenant_id, job_id, status, payload) VALUES (?, ?, ?, ?, ?)",
            (message_id, tenant, job_id, message_status, json.dumps(payload)),
        )
        conn.execute(
            "INSERT INTO audit (tenant_id, event, trace_id, details) VALUES (?, ?, ?, ?)",
            (tenant, "message_drafted", thread_id, json.dumps({"message_id": message_id})),
        )
    return {"id": message_id, "job_id": job_id, "status": message_status, **payload}


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
        live = payload.get("marketplace") == "upwork"
        if live != _live_mode():
            raise HTTPException(
                status_code=409, detail="Open this reply in its original marketplace mode."
            )
        _resume_conversation(payload["graph_thread_id"], approved=True)
        simulation = None
        if not live:
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
        next_status = "ready_to_copy" if live else "approved"
        if live:
            send_status = "Copy the draft into your Upwork conversation for final review."
        elif simulation is None:
            send_status = "disabled; no message was sent"
        else:
            send_status = "sent to local GigSim; outcome is simulated"
        result = {
            "id": message_id,
            "status": next_status,
            "external_send": send_status,
        }
        if simulation is not None:
            result["simulator_result"] = simulation
        with connection() as conn:
            conn.execute(
                "UPDATE messages SET status=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND tenant_id=?",
                (next_status, message_id, tenant),
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
