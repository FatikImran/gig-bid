<p align="center">
  <img src="docs/images/gigbid-demo.gif" alt="30-second GigBid inbox, safety review, and proposal walkthrough" width="900">
</p>

# GigBid — Evidence-first Freelancer Copilot

GigBid screens jobs, flags unsafe requests, matches them to portfolio evidence, and drafts proposals
for human review. The optional local simulator can persist approved proposals and generate synthetic
client outcomes. Local Upwork browsing connects through the official MCP server using the account
owner's OAuth consent. [Upwork setup](docs/UPWORK_SETUP.md)

> **Safety note:** Upwork mode supports job browsing. Proposal and message approval actions use
> the local simulator when configured, with fictional Connects.

## Live deployment

- **Web app:** [genuine-art-production.up.railway.app](https://genuine-art-production.up.railway.app/)
- **API health:** [gig-bid-production.up.railway.app/health](https://gig-bid-production.up.railway.app/health)

The hosted app currently uses the bundled synthetic sample jobs and a single API bearer token.
It is not connected to the instructor's simulator, hidden evaluation data, or Upwork. Keep the
reviewer token out of this repository and provide it only through the private Classroom comment.

## Screens

### Inbox and recommendation
![GigBid job inbox](docs/images/ui-inbox.png)

### Evidence-backed proposal review and approval
![GigBid proposal studio](docs/images/ui-proposal.png)

Regenerate the 30-second walkthrough with `python -m evals.runners.render_demo_gif`.

If screenshots are missing in a fresh checkout, start the API and React app using
[Getting Started](docs/GETTING_STARTED.md), then recreate them locally.

## Architecture

```mermaid
flowchart LR
  UI[React + TypeScript] --> API[FastAPI · bearer token]
  API --> DB[(SQLite + LangGraph checkpoint)]
  API --> BG[Bid graph]
  BG --> P{Parallel: Analyst · Risk · Fit}
  P --> D[Decision + Price]
  D --> W[Writer + claim verifier]
  W --> C[Critic: up to 2 revisions]
  C --> G[Compliance]
  G --> I[[Human approval interrupt]]
  I -->|approved| R[Local simulator write, if configured]
  API --> MCP[Portfolio · Marketplace · Workspace MCP]
```

See [Architecture](docs/ARCHITECTURE.md), [MCP tools](docs/TOOLS.md), and
[deployment/service setup](docs/DEPLOYMENT.md).

## Evaluation results

The 50-case [local dev set](evals/datasets/local_dev.json) uses ten authored briefs across three
synthetic personas. Each persona has five portfolio records, which leaves limited room for
Recall@5 to distinguish retrieval variants.

| Retrieval variant | Recall@5 | MRR | nDCG@10 |
|---|---:|---:|---:|
| V0 token-vector cosine | 1.000 | 0.857 | 0.893 |
| V1 requirement decomposition | 1.000 | 0.760 | 0.821 |
| V2 hybrid RRF | 1.000 | 0.903 | 0.928 |
| V3 lexical reranking | 1.000 | 0.867 | 0.901 |
| V4 outcome-aware | 1.000 | 0.903 | 0.928 |
| V8 corrective retrieval | 1.000 | 0.903 | 0.928 |

See [retrieval results](evals/results/local_dev_retrieval.json),
[judge calibration](evals/results/judge_calibration.json), and the
[blind classmate panel](evals/results/blind_proposal_panel_summary.json).

### Starter smoke benchmark

Generated locally by `python -m evals.runners.run_demo_eval`; source metrics:
[`evals/results/demo_eval.json`](evals/results/demo_eval.json). The dataset is two bundled synthetic
jobs and one evidence item, not the instructor dev/hidden set. This tiny set is a smoke test only.

| Variant | Evidence Recall@5 | nDCG@10 | Unsupported claims / proposal | Judge score | Reply rate | p95 latency | Cost / proposal |
|---|---:|---:|---:|---:|---:|---:|---:|
| V0 token-vector cosine | 1.00 | 1.00 | N/A per variant | N/A | N/A | N/A per variant | N/A |
| V1 requirement decomposition | 1.00 | 1.00 | N/A per variant | N/A | N/A | N/A per variant | N/A |
| V2 hybrid RRF (current) | 1.00 | 1.00 | 0.00* | N/A | N/A | See results JSON** | No API; local cost unmeasured |
| V3 lexical reranking | 1.00 | 1.00 | N/A per variant | N/A | N/A | N/A per variant | N/A |
| V4 outcome-aware | 1.00 | 1.00 | N/A per variant | N/A | N/A | N/A per variant | N/A |
| V8 corrective retrieval | 1.00 | 1.00 | N/A per variant | N/A | N/A | N/A per variant | N/A |

`*` One proposal from the shipped V2 pipeline; this is not a per-variant ablation.  
`**` Combined in-process retrieval p95 across six calls, not end-to-end proposal latency.

Decision and scam-detection F1 are both 1.00 on the two local examples. The measured in-process
retrieval p95 is reported in the results JSON; it is not end-to-end latency. Before/after unsupported
claims are both 0.00 per proposal in the one locally drafted proposal. A separate local synthetic
simulator experiment follows; those generated outcomes are not marketplace evidence.

### Local synthetic simulator outcomes

The simulator evaluates 50 eligible postings from a deterministic 1,000-posting Kaggle-derived
candidate pool. It compares a generic template with the evidence-grounded draft against the
simulator's deterministic synthetic client preferences. This is a simulator sanity test, not a
valid real-client A/B experiment.

| Draft strategy | Simulated proposals | Synthetic reply/interview/hire rate | Synthetic hire rate |
|---|---:|---:|---:|
| Generic template | 50 | 16% | 6% |
| Evidence-grounded draft | 50 | 82% | 66% |

These are synthetic rule-generated outcomes, designed in part to reward relevance and personalization.
They must not be interpreted as expected Upwork reply or hire rates. The full breakdown is
[`evals/results/gigsim_eval.json`](evals/results/gigsim_eval.json); methodology and caveats are in the
[R&D report](docs/RND_REPORT.md).

### X5 negotiation coach

The review-only negotiation subgraph parsed and checked 40 authored offers across three synthetic
personas. Walk-away precision/recall were both 1.00 on five cases, with zero below-floor counters.
The deterministic synthetic buyer rule accepted 22 of 35 actionable offers/counters (62.9%); mean
achieved rate change on accepted cases was +11.1% versus the initial offer. This is not a real-client
acceptance estimate; see [`evals/results/negotiation_eval.json`](evals/results/negotiation_eval.json).

### Agent architecture comparison

| Architecture | Completed / attempted | Correct / completed | Unsupported sentences / drafts | Median seconds |
|---|---:|---:|---:|---:|
| Single ReAct | 27 / 50 | 27 / 27 | 25 / 7 | 11.22 |
| Prebuilt supervisor | 28 / 50 | 27 / 28 | 28 / 6 | 23.10 |
| Hand-built graph | 43 / 50 | 43 / 43 | 0 / 3 | 0.008 |

Groq rate limits reduced coverage. The 23 jobs completed by all three designs were all decided
correctly. See [per-job results](evals/results/architectures.json) for the matched comparison,
token counts, policy blocks, and offline simulator outcomes.

The [three-minute demo](https://drive.google.com/file/d/1Uwdc9raaWPYdzyiXXXCgdgrCeBzIgED1/view?usp=sharing)
shows the proposal and reply approvals, scam, and injection examples in the local simulator.
See the report for experiment limitations and outstanding hosted instrumentation.

## Run locally

```powershell
python -m pip install -e ".[dev]"
$env:GIGBID_API_TOKEN = "set-a-long-random-local-token"
uvicorn apps.api.main:app --reload --port 8000
```

In another terminal:

```powershell
cd apps\web
npm ci
npm run dev
```

Open `http://localhost:5173`, enter the API token, and inspect the sample jobs. To include the
locally downloaded Kaggle postings and run the local simulator, see
[Getting Started](docs/GETTING_STARTED.md). For Docker, see [Runbook](docs/RUNBOOK.md).

## Assignment deliverables

- [R&D report PDF](docs/RND_REPORT.pdf) and [editable report](docs/RND_REPORT.md).
- [Three-minute demo video](https://drive.google.com/file/d/1Uwdc9raaWPYdzyiXXXCgdgrCeBzIgED1/view?usp=sharing) and
  [technical write-up draft](docs/TECHNICAL_WRITEUP_DRAFT.md).
- [Diagrams generated from code](docs/GRAPHS.md) and synthetic graph traces for [skipped scam](docs/GRAPH_TRACES.md#skipped-scam),
  [approved proposal](docs/GRAPH_TRACES.md#approved-proposal), [Critic loop](docs/GRAPH_TRACES.md#critic-loop), and
  [crash and resume](docs/GRAPH_TRACES.md#crash-and-resume).
- [Portfolio MCP run/install guide](mcp_servers/portfolio/README.md) documents installation from
  this public GitHub repository with `uvx`; there is no PyPI release.

## Repository

Public source: [github.com/FatikImran/gig-bid](https://github.com/FatikImran/gig-bid).

## Résumé bullet

- Built and deployed GigBid, a LangGraph proposal copilot with evidence retrieval and human approval.  
  Evaluated six retrieval variants on 50 synthetic cases and calibrated a claim judge on 30 labels (Cohen’s κ = 1.00).

## Known gaps

See [Implementation Checklist](docs/IMPLEMENTATION_CHECKLIST.md). In particular, the local
simulator uses deterministic synthetic client preferences/outcomes, not the instructor's hidden
simulator; the Kaggle-derived seed is local and ignored by Git. The deployed app currently has no
simulator service configured, so its approval preview does not send externally. Neural dense
retrieval, live proposal preview verification, GitHub MCP, production multi-user identity, hosted tracing,
and external publication of the technical write-up
remain incomplete. The Messages screen accepts manually entered messages rather than loading an
inbox; Agent runs shows minimal audit events rather than streamed traces; Portfolio has no
upload/GitHub ingestion; and Settings does not enforce a weekly Connects budget.
