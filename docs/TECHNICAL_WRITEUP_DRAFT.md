# What perfect recall hid in GigBid’s proposal workflow

When I started GigBid, the natural assumption was that a more sophisticated retrieval stack would
make the proposal writer more convincing. A freelance listing may contain several separate asks;
portfolio items may describe the same project in different ways; outcome labels can tell us which
past proposal got a reply. Requirement decomposition, hybrid retrieval, reranking, and outcome-aware
boosting all sound like improvements. My first test gave all six variants perfect recall. A larger
synthetic benchmark showed why recall alone missed the difference I was looking for.

I started with two bundled synthetic jobs and a one-item evidence index. One job requests a paid
classification baseline, with `evidence-001` as its relevant portfolio item. The other requests an
unpaid production dashboard and shifts communication off platform. That gave me two checks on
whether the application could route a promising job to review and stop on an obvious risk signal.
For retrieval, it offered one positive query and one possible evidence item.

I compared six configurations: token-vector cosine as V0, requirement decomposition as V1,
BM25-style lexical ranking fused with token cosine as V2, a lexical reranker as V3, an outcome-aware
boost as V4, and corrective retrieval as V8. On the only positive retrieval query, each variant
returned the only relevant item. Every configuration therefore scored 1.00 for Recall@5, MRR, and
nDCG@10. The current result file reports measured combined retrieval p95 over six in-process calls.
That number does not include the API, graph, model generation, or marketplace. Since each query had
one evidence item available, a tie was inevitable. The experiment cannot tell us whether hybrid
retrieval helps when there are hundreds of projects, ambiguous requirements, or competing evidence.

I then wrote ten briefs for an AI engineer, a full-stack developer, and a data analyst. For each brief
I prepared five conditions covering eligible work, a budget below the freelancer’s floor, an unpaid
trial, off-platform contact, and missing qualifications. I assigned a primary relevant evidence item
and recorded the expected decision, risk, and price band before running the benchmark. This produced
50 labeled synthetic cases. Because the variants share briefs, the number of distinct work requests is
still ten. Each persona has five fictional portfolio records.

Every variant still scored 1.00 at Recall@5. Since the cutoff covers the whole persona corpus, the
metric had little room to distinguish rankings. Mean reciprocal rank did. V0 scored 0.857, V1 scored
0.760, and V2, V4, and V8 tied at 0.903. My hypothesis that requirement decomposition would improve
rank over V0 failed on this set. A list of required skills can discard the part of a brief that describes
the deliverable. For example, Python and pandas alone could point to either tabular data preparation
or campaign analysis. Missing-value checks and feature cleaning discriminate between them.

I kept V2 as the default. Its BM25 and token-cosine fusion keeps exact tool names visible, preserves
the surrounding language, and shares the highest observed ranking scores. The test used lightweight
lexical components throughout. To measure whether a neural ranker earns its cost, I would need more
than five projects per persona and candidates that mention similar techniques while describing different
work. That setting would also let Recall@5 vary.

The decision metrics had the same limitation. On the two sample jobs, bid-or-skip F1 was 1.00, and
the scam-signal precision and recall were each 1.00. The paid churn-model baseline is the bid
example; the second listing asks for a full unpaid production dashboard and external messaging, so
the expected action is skip. The classifier's success means it handled those two obvious examples.
It says nothing about false positives on a subtle but legitimate listing or false negatives on a
carefully disguised scam. Those require a larger, independently labeled set.

The strongest evidence that retrieval and writing need separate checks came from three classmates.
They independently rated six anonymized pairs of completed GPT-OSS drafts, with model position
balanced across pairs. Out of 18 ratings, eight favored 20B, two favored 120B, and eight were ties.
They noticed that describing a prior classification experiment as churn-specific went beyond the
portfolio summary, even though the current job was about churn. They also flagged a wrong evidence
identifier and wording that turned one prior project into several. Both proposals sometimes described
past work without explaining how the freelancer would handle the new job.

The pipeline’s claim checker splits a letter into sentences and uses lexical overlap with the supplied
evidence. That catches some unsupported wording and lets the critic request revisions. It can still
pass a sentence whose vocabulary resembles the source while its meaning changes. Separately, I
independently labeled 30 synthetic excerpts for whether the evidence supported their past-work claims,
then sent the excerpts without my labels to GPT-OSS 120B. It agreed on all 30, giving a Cohen’s kappa
of 1.00. The excerpts reused patterns across ten briefs. The calibration supports this narrow binary
task and leaves the harder quality judgments, such as the reviewer examples, open.

The design emphasizes clear action boundaries instead of autonomous throughput. A hand-written
LangGraph graph fans out the Job Analyst, Risk Assessor, and Fit Matcher. The graph reaches a
LangGraph interrupt with the draft, evidence, risk result, price rationale, and a dry-run Connects
preview. SQLite stores the checkpoint; an integration test creates a pending approval, closes the
API test client, starts it again, and resumes the same thread. When configured, the approved action
goes through the marketplace port to our local GigSim-style REST service and spends fictional
Connects. A separate ASGI integration test checks the REST adapter. This is not the instructor's
GigSim and does not send anything to Upwork.

One failure I caught illustrates why the distinction matters. My first injection scoring pass gave
the prompt-injection flag a score below the skip cutoff. A focused test showed that text asking the
system to ignore previous instructions could still lead to a bid recommendation. I changed the
configuration-backed risk handling so that this signal is high risk, then verified that the job
routes to skip. The test only checks a known phrase; it does not establish a robust defense against
paraphrases, obfuscation, multilingual attacks, or indirect instructions in attachments. A useful
next experiment would measure attack success on an independently authored red-team set and inspect
both model following and downstream tool calls.

Operational failures were also informative. The editable install first failed because Python
package discovery saw multiple top-level directories. Explicit package inclusion fixed it.
TypeScript initially lacked the React declaration and Vite environment types; adding those types
made the production build pass. Browser testing surfaced a CORS-origin mismatch when opening the
application at the loopback IP while the API allowed the documented `localhost` origin. These are
ordinary implementation faults, but the exercise reinforced that end-to-end behavior includes
packaging and the browser boundary, not just an agent graph.

For the Writer and Critic profile comparison I ran both 20B and 120B through the same 50-case set.
Both reached approval on every eligible case they finished, but Groq throttled seven eligible 20B
cases and six eligible 120B cases. The completed draft medians were about 4.59 and 4.43 seconds.
Estimated token cost for the full attempts was about $0.00333 and $0.00564. Those totals include
measured usage from incomplete cases, and comparing medians over the completed subsets can obscure
which jobs were affected. The local simulator reports separate synthetic reply and hire outcomes for
its fictional clients.

For the same reason, the correct decision is not “the most advanced RAG variant wins.” The decision
is “keep the smallest understandable baseline until there is enough representative evidence to
choose.” With the actual persona datasets, I would first freeze the evaluation jobs and gold
evidence, define a hypothesis, run all variants on multiple jobs and personas, then ablate
requirement decomposition, lexical fusion, reranking, and outcome signals independently. I would
report confidence intervals, retrieval failures, and cases where higher Recall@5 failed to improve
proposal quality or simulated replies. The assignment's hidden set must remain untouched until the
final declared evaluation.

The experiment changed what I look at before adding a retrieval component. I want rank within the
corpus, the exact claim that reached the reviewer, how often a draft reached review, and evidence for
any simulated outcome. Those measurements answer different questions. A highly ranked case study can
still be misquoted, and a well-grounded proposal can still omit the plan a client needs to see. Both
showed up in this small evaluation. The implementation, dev cases, and result files are available in
the [GigBid repository](https://github.com/FatikImran/gig-bid).
