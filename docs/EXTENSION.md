# Signature extension: X5 negotiation coach

The conversation graph routes negotiation messages through a dedicated subgraph: it parses a stated
amount and unit, selects the active synthetic persona's hourly or project floor, checks the listing
budget ceiling, then returns an accept, counter, walk-away, or clarification recommendation. Replies
remain in the existing human-review interrupt; the subgraph never sends a message or commits a rate.

`python -m evals.runners.evaluate_negotiation` evaluates 40 authored synthetic offers across three
fictional personas. The current run reports 1.00 walk-away precision and recall on five cases, zero
below-floor counteroffers, and 22 accepted offers/counters among 35 actionable cases (62.9%) under a
deterministic synthetic buyer-ceiling rule. The mean accepted rate change relative to the initial
offer is +11.1% in that same synthetic simulation. Case-level results are in
[`evals/results/negotiation_eval.json`](../evals/results/negotiation_eval.json).

This is a control study on authored data, not evidence of real client acceptance, market-rate
outcomes, or instructor GigSim compatibility. It does not model negotiation history, project scope
changes, currency conversion, or client-specific willingness to pay. A real negotiation study still
requires the instructor's offers/labels or a separately validated simulator.
