# Three-minute GigBid demo script

This script is for a screen recording of the local prototype. The personas, job examples, simulator,
Connects, and outcomes are synthetic. Do not imply that proposals are sent to Upwork or that the
local simulator is the instructor's GigSim.

## Before recording

1. Follow [Getting Started](./GETTING_STARTED.md) and start the API and web app.
2. If demonstrating the injected listing, prepare the local Kaggle seed and set
   `GIGBID_USE_KAGGLE_FEED=true`; select a job titled `Synthetic instruction-injection test`.
3. Use a disposable local API token. Do not show credentials in the recording.
4. If the local simulator is enabled, explain that an approved action changes only synthetic local
   state. Do not use a real marketplace account.

## Recording outline

| Time | Screen and action | Narration |
|---|---|---|
| 0:00–0:20 | Sign in and show the job inbox and selected synthetic persona. | “GigBid triages jobs and drafts evidence-grounded work for review. This is a local prototype using fictional profiles and simulator data.” |
| 0:20–0:55 | Open the paid sample job, review fit, risk, evidence, and price; generate and approve the proposal. | “The analysis links its claims to portfolio evidence. Approval resumes the graph. The configured destination is only the local simulator; no Upwork action occurs.” |
| 0:55–1:25 | Open the unpaid trial/off-platform job and show its skip decision and risk reasons. | “This asks for unpaid production work and off-platform contact, so the policy gate skips it before drafting.” |
| 1:25–1:55 | Open the synthetic instruction-injection listing and show its blocked/skip outcome. | “The listing text is untrusted input. Its request to reveal hidden instructions is treated as a risk signal, not followed.” |
| 1:55–2:30 | In Messages, enter a sample client offer below the persona floor; show the counter recommendation and approve the reviewed reply. | “Messages are manually entered in this prototype, not loaded from a client inbox. The negotiation coach applies this synthetic persona's floor and still requires review before the local simulator action.” |
| 2:30–2:50 | Show the X5 result file and the synthetic evaluation summary. | “Across 40 authored offers, walk-away precision and recall were 1.00 on five floor conflicts, and there were no below-floor counters. These deterministic synthetic results are not client behavior.” |
| 2:50–3:00 | Close on the README and remaining limitations. | “The instructor datasets, hosted model, public deployment, and external traces were unavailable. The report separates measured local behavior from those uncompleted requirements.” |

Keep the browser window at a readable scale, avoid exposing local file paths or tokens, and include the
README and report links in the video description after public publication.
