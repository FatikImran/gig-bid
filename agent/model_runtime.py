"""Local open-weight inference with structured responses and usage records."""

import json
import os
import threading
import time
from functools import lru_cache
from pathlib import Path

import httpx
from dotenv import load_dotenv
from jsonschema import validate

from agent.settings import ROOT, agent_config

load_dotenv(ROOT / ".env", override=False)
_lock = threading.Lock()


def enabled() -> bool:
    return os.getenv("GIGBID_MODEL_PROFILE", agent_config()["models"]["profile"]) == "open"


@lru_cache(maxsize=2)
def _model(path: str):
    from llama_cpp import Llama

    if not Path(path).is_file():
        raise RuntimeError("Open model weights are missing. See docs/MODELS.md.")
    return Llama(model_path=path, n_ctx=4096, n_threads=4, verbose=False)


def generate(node: str, payload: dict, schema: dict) -> dict:
    config = agent_config()["models"]
    settings = config["profiles"]["open"]
    path = str(ROOT / os.getenv("GIGBID_MODEL_PATH", settings["model_path"]))
    prompt = (ROOT / "agent" / "prompts" / f"{node}.md").read_text(encoding="utf-8")
    started = time.perf_counter()
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload)},
    ]
    provider = os.getenv("GIGBID_MODEL_PROVIDER", "local")
    if provider == "groq":
        key = os.getenv("GROQ_API_KEY", "").strip()
        if not key:
            raise RuntimeError("Set GROQ_API_KEY in the private .env file.")
        model_name = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        with httpx.Client(timeout=90) as client:
            reply = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model_name,
                    "messages": messages,
                    "max_completion_tokens": 1800,
                    "temperature": settings["temperature"],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": node,
                            "strict": True,
                            "schema": schema,
                        },
                    },
                },
            )
        if reply.status_code != 200:
            raise RuntimeError(f"Groq inference failed with HTTP {reply.status_code}.")
        response = reply.json()
    elif provider == "local":
        model_name = Path(path).name
        with _lock:
            response = _model(path).create_chat_completion(
                messages=messages,
                response_format={"type": "json_object", "schema": schema},
                temperature=float(os.getenv("GIGBID_MODEL_TEMPERATURE", settings["temperature"])),
                max_tokens=400,
                seed=42,
            )
    else:
        raise ValueError("GIGBID_MODEL_PROVIDER must be local or groq.")
    elapsed = time.perf_counter() - started
    result = json.loads(response["choices"][0]["message"]["content"])
    validate(result, schema)
    usage = {
        "node": node,
        "model": model_name,
        "provider": provider,
        "latency_seconds": elapsed,
        **response["usage"],
        "api_usd": (
            response["usage"]["prompt_tokens"] * 0.075
            + response["usage"]["completion_tokens"] * 0.30
        )
        / 1_000_000
        if provider == "groq" and model_name == "openai/gpt-oss-20b"
        else (0 if provider == "local" else None),
    }
    usage_path = ROOT / "data" / "processed" / "model_usage.jsonl"
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, usage_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(usage) + "\n")
    return result
