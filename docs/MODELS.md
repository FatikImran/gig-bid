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
The hosted deployment needs these weights and the inference dependency before it can serve the
open profile. Neural retrieval, per-node model routing, and the two-configuration comparison
remain separate work.
