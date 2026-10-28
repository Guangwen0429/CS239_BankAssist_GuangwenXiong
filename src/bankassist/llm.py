"""Optional LLM backend (BYOTC: bring your own token and compute).

BankAssist runs completely without an LLM: every agent has a rule-based
implementation.  If the environment variables below are set, the
ConciergeAgent uses the LLM to understand the customer's free-text request
and falls back to the rule-based parser if the LLM call fails or returns
something unusable.

Any OpenAI-compatible chat-completions endpoint works, for example a local
model served by Ollama, LM Studio, vLLM or Zeno, or a hosted API.

    BANKASSIST_LLM_BASE_URL   e.g. http://localhost:11434/v1   (required to enable)
    BANKASSIST_LLM_MODEL      e.g. llama3.1:8b                  (required to enable)
    BANKASSIST_LLM_API_KEY    only if the endpoint needs one    (optional)
"""

from __future__ import annotations

import json
import os
import urllib.request


class LLMUnavailable(RuntimeError):
    pass


def llm_config() -> dict[str, str] | None:
    base = os.environ.get("BANKASSIST_LLM_BASE_URL", "").strip()
    model = os.environ.get("BANKASSIST_LLM_MODEL", "").strip()
    if not base or not model:
        return None
    return {"base_url": base.rstrip("/"), "model": model,
            "api_key": os.environ.get("BANKASSIST_LLM_API_KEY", "").strip()}


def chat(system_prompt: str, user_message: str, timeout: float = 60.0) -> str:
    cfg = llm_config()
    if cfg is None:
        raise LLMUnavailable("LLM not configured")
    body = json.dumps({
        "model": cfg["model"],
        "temperature": 0,
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_message}],
    }).encode()
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # network error, bad JSON, missing fields ...
        raise LLMUnavailable(str(exc)) from exc
