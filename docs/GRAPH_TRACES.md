# Synthetic LangGraph traces

These local streams record graph node updates and approval states. Hosted tracing, MCP spans, and token and cost telemetry are separate work.

## Skipped scam

Bundled unpaid trial fixture.

```json
[
  {
    "node": "job_analyst"
  },
  {
    "node": "risk_assessor"
  },
  {
    "node": "fit_matcher"
  },
  {
    "node": "decision",
    "decision": "skip"
  }
]
```

## Approved proposal

Bundled paid job, resumed after the human approval interrupt.

```json
[
  {
    "node": "job_analyst"
  },
  {
    "node": "risk_assessor"
  },
  {
    "node": "fit_matcher"
  },
  {
    "node": "decision",
    "decision": "bid"
  },
  {
    "node": "price"
  },
  {
    "node": "writer"
  },
  {
    "node": "claim_verification"
  },
  {
    "node": "critic",
    "critic_approved": true,
    "revision_count": 0
  },
  {
    "node": "compliance"
  },
  {
    "node": "__interrupt__"
  },
  {
    "node": "approval",
    "approval_status": "approved"
  },
  {
    "node": "post_approval"
  }
]
```

## Critic loop

A controlled fixture forces the first Critic rejection. The retry uses the normal Critic and follows the compiled graph.

```json
[
  {
    "node": "job_analyst"
  },
  {
    "node": "risk_assessor"
  },
  {
    "node": "fit_matcher"
  },
  {
    "node": "decision",
    "decision": "bid"
  },
  {
    "node": "price"
  },
  {
    "node": "writer"
  },
  {
    "node": "claim_verification"
  },
  {
    "node": "critic",
    "critic_approved": false,
    "revision_count": 1
  },
  {
    "node": "writer"
  },
  {
    "node": "claim_verification"
  },
  {
    "node": "critic",
    "critic_approved": true,
    "revision_count": 1
  },
  {
    "node": "compliance"
  },
  {
    "node": "__interrupt__"
  }
]
```

## Crash and resume

A subprocess exits abruptly at the approval checkpoint. The parent reopens SQLite and resumes. This trace covers graph recovery through approval.

```json
[
  {
    "node": "job_analyst"
  },
  {
    "node": "risk_assessor"
  },
  {
    "node": "fit_matcher"
  },
  {
    "node": "decision",
    "decision": "bid"
  },
  {
    "node": "price"
  },
  {
    "node": "writer"
  },
  {
    "node": "claim_verification"
  },
  {
    "node": "critic",
    "critic_approved": true,
    "revision_count": 0
  },
  {
    "node": "compliance"
  },
  {
    "node": "__interrupt__"
  },
  {
    "event": "worker_exit",
    "exit_code": 17
  },
  {
    "event": "checkpoint_reopened",
    "next": "approval"
  },
  {
    "node": "approval",
    "approval_status": "approved"
  },
  {
    "node": "post_approval"
  }
]
```
