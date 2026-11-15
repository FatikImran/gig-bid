# Local open model

The default `open` profile uses Qwen2.5-0.5B-Instruct Q4_K_M through llama-cpp-python.
Writer and Critic run inference. Other nodes currently use rules and retrieval. Usage records
are appended to the Git-ignored `data/processed/model_usage.jsonl`.

Download the official weights into `data/processed/models`:

```powershell
python -m pip install llama-cpp-python
curl.exe -fL -o data/processed/models/qwen2.5-0.5b-instruct-q4_k_m.gguf https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf
```

Start the API normally to run inference. For deterministic fixture tests, set
`GIGBID_MODEL_PROFILE=fixtures`. Temperature can be set with `GIGBID_MODEL_TEMPERATURE`.
CPU inference incurs no API charge. Hardware operating costs remain unmeasured.
For hosted open-weight inference set `GIGBID_MODEL_PROVIDER=groq`, `GROQ_MODEL=openai/gpt-oss-20b`,
and `GROQ_API_KEY` in the API service environment. In local development put these values in the
Git-ignored `.env`. The requests send job and retrieved evidence to Groq. Use synthetic fixtures
for evaluation and local inference for private data.

Run the synthetic smoke comparison from the repository root. It uses the private Groq key
and will call both GPT-OSS models:

```powershell
python -m evals.runners.evaluate_open_models
```

The runner writes [per-case results](../evals/results/open_model_smoke.json) with approval-gate
outcomes, provider errors, latency, tokens, and estimated cost at standard uncached rates.
The earlier [one-job comparison](../evals/results/open_model_eval.json) is retained.
The workflow uses shared rules for bid decisions and logs model usage for Writer and Critic.
The claim metric uses the pipeline's own heuristic verifier. The instructor dev-set evaluation
and independent proposal-quality scoring remain open.

| Groq model | Drafts at approval | Median latency for drafts at approval | Estimated total API cost |
| --- | ---: | ---: | ---: |
| GPT-OSS 20B | 1 of 2 | 4.001 s | $0.000634 |
| GPT-OSS 120B | 2 of 2 | 4.519 s | $0.001507 |

Both runs skipped the risky and below-budget jobs before calling the model. In the 20B churn
case, the final draft had no text after claim verification. Use 120B for the hosted smoke test
based on draft completion in this small sample.
