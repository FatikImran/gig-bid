# Implementation checklist

## Implemented and locally verified

- [x] Typed job/risk/fit/decision/price/proposal/compliance handoffs with validation.
- [x] Single marketplace port with sample fixtures and a guarded official Upwork MCP client adapter.
- [x] Portfolio, marketplace, and workspace FastMCP local servers with typed tools/resources/prompt.
- [x] In-memory MCP client tests, bounded schemas, per-agent tool allowlists, and a checked-in tool-schema snapshot.
- [x] Marketplace MCP reads use the configured port; direct non-dry-run writes are blocked and API approval gates simulator writes.
- [x] Parallel Job Analyst, Risk Assessor, and Fit Matcher LangGraph branches.
- [x] Evidence-first writer, claim verifier, bounded critic, compliance check, and approval interrupts.
- [x] SQLite proposal/audit/idempotency and LangGraph checkpoint persistence.
- [x] Resume a pending approval after API restart in an integration test.
- [x] React/TypeScript job inbox, detail/risks, evidence-linked proposal review, pipeline preview,
  Connects dry-run, local approve/reject/edit, and API error states.
- [x] Sample RAG V0/V1/V2/V3/V4/V8 variants and generated smoke results.
- [x] API bearer-token protection, tenant-scoped queries, request validation, PII masking helper.
- [x] Worker polling prototype, Docker API/web/worker compose, and local docs.

## Blocked or incomplete (not represented as complete)

- [x] Build local GigSim-style REST API with jobs, synthetic clients/history/preferences, Connects, proposals, messages, rate limiting, idempotency, audit, and deterministic simulated outcomes.
- [x] Create and document a deterministic seed-preparation script for the locally downloaded Kaggle postings, with PII-like contact scrubbing and 40 labeled synthetic risk/injection scenarios.
- [x] Add three explicitly synthetic freelancer personas and portfolio examples; do not present them as real work.
- [x] Add a reproducible synthetic-client outcome evaluation; its reply/hire metrics are not real-marketplace results.
- [x] Implement the X5 negotiation subgraph with offer parsing, persona floors, budget walk-away rules, review-only replies, and a 40-case synthetic evaluation.
- [ ] Improve the contract dataset's role: currently only aggregate descriptive statistics are generated; no pricing model consumes it.
- [ ] Instructor's three persona corpora, gold dev sets, hidden set, and official policy update are not in the workspace; do not claim those official evaluations.
- [ ] Neural dense embeddings, true cross-encoder, vector store, PDF/GitHub ingestion, upload UI.
- [ ] Upwork OAuth authorization/callback, live write tool validation, and user-owned account.
- [ ] Third-party GitHub MCP server configuration and least-privilege token.
- [ ] Multi-user authentication and encrypted tenant OAuth storage.
- [ ] Postgres/Redis production deployment, distributed worker queue, and hosted service.
- [ ] LangSmith/Langfuse exporter, token/cost tracing, calibrated LLM judge, human panel.
- [ ] Required model-based 40-task tool-design study, three-architecture comparison, ten failed dev-job taxonomy, and instructor hidden-set metrics; the supplied dev set and local model runtime are unavailable.
- [x] Seven Playwright E2E tests covering onboarding, proposal approval/rejection/edit, conversation and negotiation replies, and degraded mode.
- [x] Twelve-case authored synthetic failure-mode regression runner and results; this is not a substitute for ten failed instructor dev jobs.
- [x] Negotiation evaluation gate reports walk-away precision/recall, accepted-counter outcomes, and below-floor counter safety.
- [x] UI sections for pipeline, messages, audit/run history, local analytics, synthetic portfolio selection, and workspace settings.
- [x] CI evaluation gate runs local smoke, simulator safety, synthetic failure-mode, and negotiation suites.
- [x] Deployed public web app and API; health, CORS, and the safe-job/risk UI flows were smoke-tested.
- [ ] Submit reviewer credentials privately; record and publish the three-minute demo; verify the public `uvx` Portfolio MCP install; publish the technical write-up.

Local test results and environment limitations are documented in
[RND_REPORT.md](./RND_REPORT.md), `evals/results/demo_eval.json`,
`evals/results/gigsim_eval.json`, and `evals/results/negotiation_eval.json`.
