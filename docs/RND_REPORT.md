# GigBid — Research and Development Report

**Course:** AI-4016 · Assignment 2  
**Student:** Muhammad Fatik · **Roll number:** 23I-0655 · **Section:** A  
**Report date:** 15 November 2026<br />
**Status:** Public Railway prototype is live in sample mode; this is not a deployed instructor GigSim submission.

## Executive summary

GigBid is an evidence-first freelancer copilot. It screens starter examples and an optional
Kaggle-derived feed, flags unpaid/off-platform or injected instructions, retrieves persona evidence,
drafts proposals, verifies claims, and waits for human approval. A hand-written LangGraph bid
workflow fans out the Job Analyst, Risk Assessor and Fit Matcher in parallel, then runs pricing,
writing, claim verification, a bounded Critic, compliance, and a persisted interrupt. A local
GigSim-style REST service stores approved simulator proposals, fictional Connects, messages, and
deterministic synthetic client outcomes. It is our substitute, not the instructor's service.

The local feed is prepared from 200 selected historical postings and 40 authored synthetic safety
scenarios; raw CSVs and derived seed are excluded from Git. Three fictional personas and all
generated client preferences/outcomes are explicitly synthetic. The instructor's GigSim, persona
corpora, gold/hidden evaluations, and updated policy are not in the workspace. Therefore retrieval
smoke metrics and local simulator outcomes are distinct, and neither demonstrates real marketplace
performance. Results are in [`evals/results/demo_eval.json`](../evals/results/demo_eval.json) and
[`evals/results/gigsim_eval.json`](../evals/results/gigsim_eval.json).

## 1. Problem and constraints

Freelancers spend time triaging listings and risk Connects on poor-fit or unsafe work. GigBid should
reduce that effort without impersonating the freelancer. The system must never follow instructions
embedded in untrusted job/client text, invent experience, contact clients off-platform, or send a
proposal/message or spend Connects without approval. Simulator approvals can submit to the local
simulator and spend fictional Connects. Upwork mode can request a preview after approval and leaves
final submission to the account owner.

Three fictional profiles and authored synthetic portfolio items are available for local fit tests.
`data/sample/jobs.json` still provides one plausible job and one unpaid off-platform trial. The
optional Kaggle feed supplies historical job descriptions; the contract dataset provides only
descriptive aggregates and does not train a pricing model. Simulator reply/hire outcomes follow
synthetic deterministic rules, not real client behavior.

## 2. Architecture and implementation

FastAPI protects the application with a bearer token. SQLite stores proposals, status changes,
idempotency records, audit events, promoted memories, worker-seen job IDs, and LangGraph checkpoints.
The hand-written bid graph uses `Send` for parallel analysis. A decision node sends risky/low-fit jobs
to a terminal state; bid candidates proceed to price, writer, verifier, critic (at most two
revisions), compliance, and `interrupt()` for human review. The API approval endpoint resumes the
checkpoint after a restart; the integration test covers close/reopen before approval. Edits are
re-checked and copied into graph state before resumption.

The conversation graph classifies question, negotiation, interview request, scam signal, or other,
then interrupts before approval. The API can send an explicitly approved draft only to the
configured local simulator. Direct non-dry-run Marketplace MCP calls are rejected, even when passed
`approved=true`; only the authenticated API's persisted approval workflow can reach simulator
writes. The same API bearer credential maps to a single local tenant; this is not multi-user
authentication or encrypted OAuth storage.

The local `gigsim.app` FastAPI service wraps the generated job/client seed and persists proposals,
messages, Connects, idempotency results, and audit metadata in SQLite. Synthetic hidden preferences
are not exposed through client-history responses. Deterministic rules produce ignored, replied,
interview, or hired proposal outcomes; requests are rate limited and a transient failure is
occasionally injected. The GigBid approval endpoint only permits local simulator hostnames and
calls the service after approval resumes. Three local FastMCP servers expose typed portfolio, configured-marketplace, and workspace tools.
Marketplace reads use the configured port; write-intent calls only preview and reject non-dry-run
requests. The account owner verified OAuth, tool discovery, job search and job detail locally
against the official Upwork MCP server using `python -m agent.upwork_marketplace`. The live OAuth
check used the CLI. The local Playwright smoke test also passed against the live adapter and
verified that the browser loaded the inbox and opened a listing. The [three-minute demo](https://drive.google.com/file/d/1Uwdc9raaWPYdzyiXXXCgdgrCeBzIgED1/view?usp=sharing)
shows the simulator workflow. The local web workflow can request
an Upwork proposal preview after approval and hand off an approved message draft to the account
owner. The live invitation and prior-proposal checks passed. Upwork rejected the authenticated
preview attempt after reporting that the account could not apply to that listing. A separate
read-only eligibility check found that the reported Connects balance was below the listed cost of
each candidate it checked. A successful live preview and a separate GitHub MCP integration remain
open.

The [code-generated diagrams](GRAPHS.md) and [synthetic graph traces](GRAPH_TRACES.md) can be
regenerated with `python -m evals.runners.capture_graph_evidence`. The recovery trace reopens a
persisted approval checkpoint after an abrupt subprocess exit. These traces record graph updates
and approval states. Hosted end-to-end spans and token/cost telemetry remain open.

The React UI supplies Pipeline, Messages, Agent runs, Analytics, Portfolio, and Settings sections,
along with job/risk/evidence review, proposal editing, approval/rejection, and Connects preview.
Local simulator submission is distinguished from real marketplace activity. Important limitations
remain: Messages accepts user-entered messages rather than reading a client inbox; Agent runs shows
minimal audit events rather than streamed node traces; Portfolio has no upload/GitHub ingestion; and
Settings does not enforce a weekly Connects budget. See
[the implementation checklist](./IMPLEMENTATION_CHECKLIST.md).

## 3. R&D question A — MCP tool design

**Question:** does tool granularity and description quality change tool selection or arguments?
**Experiment status:** not measured. The required 40-task tool-selection benchmark and known correct
calls are still absent. The 40 synthetic risk scenarios test policy behavior, not tool selection.
We do not claim tool-selection accuracy, argument accuracy, or token counts.

What was verified is narrower: local FastMCP tools are typed, bounded, and annotated; in-memory
MCP client tests exercise listing and calls; a schema snapshot fails CI on tool-contract changes;
portfolio search returns synthetic evidence; marketplace tools use the configured port; and write
previews reject missing approval. The simulator REST API rejects unapproved actions and handles
idempotency; workspace holds reject unapproved requests. These checks are not a substitute for a
model-based tool-selection study. The exact tool surface is listed in
[`docs/TOOLS.md`](./TOOLS.md).

## 4. R&D question B — retrieval and claim verification

**Hypothesis.** Requirement decomposition improves mean reciprocal rank over V0. The
50-case synthetic dev set (ten briefs crossed with five conditions across three personas) was
evaluated with `python -m evals.runners.evaluate_local_retrieval`.

| Variant | Evidence Recall@5 | MRR | nDCG@10 |
|---|---:|---:|---:|
| V0 token-vector cosine | 1.000 | 0.857 | 0.893 |
| V1 requirement decomposition | 1.000 | 0.760 | 0.821 |
| V2 BM25/token-cosine RRF | 1.000 | 0.903 | 0.928 |
| V3 lexical reranking | 1.000 | 0.867 | 0.901 |
| V4 outcome-aware ranking | 1.000 | 0.903 | 0.928 |
| V8 corrective retrieval | 1.000 | 0.903 | 0.928 |

V1 lost rank quality on this benchmark. The pipeline retains V2, which tied for the highest
MRR and nDCG@10. Recall@5 saturated with five evidence records per persona. Related dev cases
share a brief and relevance labels. The breakdown is in
[retrieval results](../evals/results/local_dev_retrieval.json).

**Judge calibration.** The student independently labeled 30 shuffled synthetic excerpts for
past-work claim support. GPT-OSS 120B scored the same cases with the human labels withheld.
Agreement was **30/30 (100%)** and **Cohen’s κ = 1.00**. Both raters marked 20 supported and
10 unsupported. The excerpts use repeated patterns based on ten briefs. This measures agreement
on claim support in those examples. [Calibration results](../evals/results/judge_calibration.json).

**Blind classmate panel.** Three reviewers rated six matched proposal pairs covering all three
personas. Model identities were hidden and A/B placement was balanced. Of 18 ratings, **8 favored
20B, 2 favored 120B, and 8 were ties**. Reviewers preferred drafts that stayed focused on the brief
and matched the evidence closely. They flagged an overstated project domain, an incorrect evidence
identifier, and claims that turned one prior project into several. Both models often described
past work with little detail about the proposed approach. Only pairs where both drafts reached
approval were included, so the results describe preferences among completed drafts on this small
synthetic sample. [Panel tally](../evals/results/blind_proposal_panel_summary.json).

On the one bid-eligible sample job, the proposal had **0 unsupported sentences before and 0 after**
the verifier. This is a one-proposal sample and does not establish a general hallucination rate. The
checker uses conservative token overlap against the included evidence and removes any sentence below
its support threshold; semantic entailment is not guaranteed. The current result file records
retrieval p95 over six in-process retrieval calls; this is not
end-to-end latency and excludes API, graph, model, and marketplace time. No paid API was called;
token usage and production USD/job are not applicable. A separate local simulator evaluation now
reports deterministic reply/hire outcomes for eligible proposals, but those are generated labels
and are not real client outcomes.

### Synthetic client outcome comparison

`python -m evals.runners.evaluate_gigsim` selected 50 eligible postings from a deterministic
hash-ordered, 1,000-row cap of the Kaggle-derived corpus. For each, the best-fitting eligible
synthetic persona submitted two drafts to the deterministic outcome rule: a generic template and
the current evidence-grounded draft. The local rule counts interview and hire as replies.

| Draft | Proposals | Reply/interview/hire | Hire |
|---|---:|---:|---:|
| Generic template | 50 | 16% | 6% |
| Evidence-grounded draft | 50 | 82% | 66% |

This large difference is expected in part because the simulator explicitly rewards job relevance,
preferred terms, and personalized openings. It is an implementation/sanity check, not an independent
experiment or estimate of real client behavior. The 40 synthetic unpaid/off-platform and injection
fixtures were all skipped (40/40); they were authored to exercise those existing safety rules, so
this is not general scam recall. Full counts and limitations are in
[`evals/results/gigsim_eval.json`](../evals/results/gigsim_eval.json). The baseline retrieval smoke
runner separately leaves reply/hire values null; it does not call the simulator.

## 5. R&D question C — orchestration

The three designs attempted the same 50 synthetic jobs using GPT-OSS 120B. The single ReAct agent
had inspection, pricing, draft review and result tools. The prebuilt `langgraph-supervisor` routed
between a triage agent and a drafting agent. The hand-built graph used deterministic triage and
model-based Writer and Critic nodes. All returned drafts were evaluated with a shared heuristic
claim checker and policy gate. Only passing drafts entered the local offline GigSim scorer.

| Architecture | Completed / attempted | Correct / completed | Unsupported sentences / drafts | Violations caught | GigSim replies / scored | Tokens | Median seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| Single ReAct | 27 / 50 | 27 / 27 | 25 / 7 | 5 | — / 0 | 46,656 | 11.22 |
| Prebuilt supervisor | 28 / 50 | 27 / 28 | 28 / 6 | 5 | — / 0 | 82,479 | 23.10 |
| Hand-built graph | 43 / 50 | 43 / 43 | 0 / 3 | 0 | 2 / 3 | 8,896 | 0.008 |

Groq rate limits accounted for incomplete runs. Tokens reflect the latest saved attempt per job;
median latency covers completed jobs and includes any retry wait. The 23 jobs all three designs
completed were all decided correctly by all three. On those jobs, the two agent-driven designs
returned 13 and 14 sentences that the heuristic verifier could not support, respectively, across
three drafts each. The hand-built graph returned zero across its three drafts. The shared gate
withheld all comparable ReAct and supervisor drafts, leaving their reply rates undefined. The
hand-built graph had fewer model calls on skip cases. Its simulator outcome sample is small.
I retain the hand-built graph for its explicit policy, claim verification and approval steps.
See [per-job results](../evals/results/architectures.json) and the
[evaluation procedure](MODELS.md#architecture-evaluation).

The hand-written graph's functional behavior was tested: its analysis branches run in parallel, a
safe sample reaches the proposal approval interrupt, a risk signal exits before approval, and a
checkpoint resumes after the API test client is restarted. The Python suite includes these
integration paths. The [four trace examples](GRAPH_TRACES.md) capture a scam skip, an approved
proposal, a forced Critic revision and a crash-and-resume. The [compiled graph diagrams](GRAPHS.md)
include the bid and conversation workflows. The runner also saves the ReAct and supervisor diagrams.

## 6. Change request, memory, and signature extension

The assignment describes a 2 November 2026 policy update, but that updated policy file was not in the
workspace. The local policy is therefore the illustrative starter policy, not the grading source of
truth. Risk terms and prohibited terms now live in `data/policy_pack/policy.yaml`, fit/risk thresholds
and RAG selection live in `agent/config.yaml`, and each agent prompt is a separate file. Applying a
future rule can be localized to that policy file plus focused tests. We cannot report the actual
instructor update, measured edit time, or line count.

Style memory promotion requires at least three consistent user edits; outcome memory requires a
verified marketplace result and explicit user approval. The SQLite store separates style and outcome
records by tenant and allows listing/deletion. Raw tool output is not promoted. This memory flow is
not yet exposed through a settings UI.

The selected extension is an **X5 negotiation coach**. Negotiation messages pass through an offer
parser, persona-specific floor and listing-ceiling rules, and a response drafter before the existing
human-review interrupt. In 40 authored synthetic offers, walk-away precision and recall were both
1.00 on five floor/ceiling conflict cases, and no counteroffer fell below the selected profile floor.
A deterministic synthetic buyer rule accepted 22 of 35 actionable offers/counters (62.9%); the mean
accepted rate change versus the initial offer was +11.1%. These figures describe only the authored
simulator rule, not real client negotiations or GigSim. The complete result and caveats are in
[`evals/results/negotiation_eval.json`](../evals/results/negotiation_eval.json) and
[`docs/EXTENSION.md`](./EXTENSION.md).

## 7. Failures, safety, and operations

### Ten observed dev-job failures

These cases come from the authored dev benchmark. The architecture run records the generated
drafts and the shared gate's decisions. Provider throttling rows describe observed attempts.

| Dev case | Failure category and observation | Mitigation tried and observed result |
|---|---|---|
| 01 · churn | Generic opening and broken evidence IDs in the ReAct draft | The shared gate found no supported evidence links and withheld simulated submission. |
| 02 · threshold review | Supervisor skipped a job labeled bid | The hand-built workflow's explicit fit and budget rules selected bid. |
| 03 · tabular cleaning | ReAct and supervisor each returned three sentences the heuristic could not verify | The shared gate withheld both drafts from simulator scoring. |
| 04 · React portal | ReAct introduced guarantee language | The shared compliance check caught the policy term and withheld the draft. |
| 05 · Node.js API | ReAct cited identifiers absent from the portfolio and overstated an AWS deployment outline | The shared claim check withheld the draft. |
| 06 · Shopify | Groq HTTP 429 interrupted all three model paths on a pass | The runner retained the failures and supports targeted retries from its saved results. |
| 07 · cloud packaging | Groq HTTP 429 interrupted model completion on a pass | Long retry windows were recorded so the run could pause without discarding other jobs. |
| 08 · Excel trends | ReAct claimed the prior analysis yielded actionable insights beyond the supplied summary | ReAct had no supported evidence links under the shared checker and its draft was withheld. |
| 09 · Power BI | ReAct used citation identifiers absent from the portfolio | The shared gate withheld the draft after failing to verify its evidence links. |
| 10 · SQL reconciliation | Groq HTTP 429 interrupted all three model paths on a pass | The runner saved the job's failed attempts for later retry. |

The guard's blocks prevent unverified proposals from entering the offline simulator. They do
not establish that every blocked sentence was semantically wrong. Future work should score
past-work claims independently of proposed future steps.

Observed engineering failures and corrections:

1. Editable Python installation initially failed because setuptools discovered multiple top-level
   packages; explicit package discovery was added.
2. The first injection test showed an injected prompt signal below the skip threshold; policy-backed
   risk scoring now reaches the high-risk decision threshold.
3. API tests initially skipped application lifespan setup and failed to create proposal tables;
   tests now use the full lifespan and startup initializes both API tables and graph checkpoints.
4. Browser validation exposed a CORS-origin mismatch when opening the UI at `127.0.0.1`; supported
   local development uses the documented `localhost` origin.
5. TypeScript compilation initially failed because React declarations and Vite environment types
   were missing; those type dependencies/declarations were added.

These are implementation/debugging incidents, **not ten failed marketplace jobs**. To exercise
failure handling without inventing dev-set observations, `python -m
evals.runners.evaluate_failure_modes` runs twelve authored synthetic regression cases. All twelve
pass in the current result file, including bid/skip decisions, unsupported claims, compliance,
injection in jobs and messages, hourly/fixed pricing, idempotent retry, rate limiting, and injected
transient failures. The full case-by-case evidence is in
[`evals/results/failure_modes.json`](../evals/results/failure_modes.json). These are control tests,
not observed failures, and do not satisfy the requested ten failed instructor dev jobs.

The local protections include bearer authentication, parameterized DB queries, tenant filters,
bounded Pydantic requests, idempotency keys, persistent approval checkpoints, policy-configured
risk/compliance checks, PII masking helper, and fail-closed external actions. Audit records omit
message and proposal body text. The local worker polls conservatively and deduplicates job IDs.
There is no hosted tracing service, distributed queue, Postgres/Redis setup, or encrypted OAuth
store. The web app and API are deployed on Railway at
[genuine-art-production.up.railway.app](https://genuine-art-production.up.railway.app/) and
[gig-bid-production.up.railway.app](https://gig-bid-production.up.railway.app/health). The hosted
app uses the bundled synthetic examples, a shared API bearer token, and SQLite; it has no simulator
service configured and does not send externally. Health, CORS, the safe-job review, and the
high-risk skip path were smoke-tested. This is not an instructor GigSim deployment. The
single-user prototype should not be exposed as a production SaaS without the upgrades in
[`DEPLOYMENT.md`](./DEPLOYMENT.md).

## 8. Reproducibility and final outcome

The `open` profile now runs the Writer and Critic with open-weight inference. An initial
[comparison on one synthetic job](../evals/results/open_model_eval.json) ran GPT-OSS 20B and 120B
on Groq. Both reached the approval gate. The 20B run took 11.16 seconds with one revision and
an estimated API cost of $0.00110. The 120B run took 5.65 seconds with no revision and an
estimated API cost of $0.00076. These one-case estimates depend on generation length and queue time.
On the 50-case local dev set, 20B reached approval on 3 of 10 eligible cases and 120B on 4 of 10.
Groq rate-limited the other eligible cases after a short retry. All completed drafts reached
approval, leaving relative proposal quality unresolved. The measured median for those drafts was
4.59 seconds for 20B and 4.43 seconds for 120B. Estimated costs across each run were $0.00333
and $0.00564, respectively. A fresh evidence-cited draft reached review in the hosted app after
the Groq key was configured. [Dev-set model results](../evals/results/local_dev_groq.json).

The latest recorded Python suite passed **58 tests**, the standard Playwright suite passed **8 tests**, the
React production build succeeded, Ruff passed, and `docker compose ... config --quiet` passed. The
generated metrics and SVG figure can be reproduced locally. These checks do not replace the required
GigSim hidden test, private reviewer credential delivery, public traces, video submission, or
published technical write-up. The public app URL is live; its reviewer login must be shared only in
the private Classroom comment.

**What ships:** a prepared local Kaggle-derived feed, a distinct local deterministic simulator with
synthetic outcomes, approval-safe LangGraph graphs, SQLite checkpoints, three local MCP servers,
six lightweight RAG variants, claim filtering, local Upwork browsing, and partial workspace UI
screens. **Open work:** live marketplace drafts, instructor GigSim compatibility, neural embeddings/reranking,
multi-user production identity, architecture-comparison evidence, hosted tracing, or the remaining
message-inbox, portfolio-ingestion, and budget-enforcement workflows. The prior verification of the
public GitHub-based Portfolio MCP install at `92772fa` listed all three tools and successfully called
`list_portfolio_skills`. See the [Portfolio MCP install guide](../mcp_servers/portfolio/README.md).
