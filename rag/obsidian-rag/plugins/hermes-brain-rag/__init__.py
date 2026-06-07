"""Hermes plugin for automatic Hermes Brain RAG lookup.

Copy this directory to `~/.hermes/plugins/hermes-brain-rag/`, enable it with
`hermes plugins enable hermes-brain-rag`, then restart Hermes/gateway.

The plugin is intentionally dependency-free. It does not import LlamaIndex or
Qdrant clients into the Hermes process; it calls the local RAG API endpoint and
fails closed if the service is unavailable.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_CONTEXT_URL = "http://127.0.0.1:8000/api/context"


def _message_get(message: Any, key: str, default: str = "") -> Any:
    if isinstance(message, dict):
        return message.get(key, default)
    return getattr(message, key, default)


def _latest_user_prompt(messages: list[Any] | None = None, user_message: Any = None) -> str:
    if user_message:
        return str(user_message)
    for message in reversed(messages or []):
        if _message_get(message, "role") == "user":
            return str(_message_get(message, "content", ""))
    return ""


def _request_context(prompt: str) -> str:
    api_key = os.getenv("HERMES_BRAIN_RAG_API_KEY") or os.getenv("API_KEY", "")
    if not api_key:
        return ""

    url = os.getenv("HERMES_BRAIN_RAG_CONTEXT_URL", DEFAULT_CONTEXT_URL)
    timeout = float(os.getenv("HERMES_BRAIN_RAG_TIMEOUT", "2.5"))
    body = json.dumps({"prompt": prompt}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload.get("context") or "")


def rag_pre_llm_call(messages: list[Any] | None = None, user_message: Any = None, **kwargs):
    prompt = _latest_user_prompt(messages=messages, user_message=user_message)
    if not prompt.strip():
        return None
    try:
        context = _request_context(prompt)
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return None
    if context.strip():
        return {"context": context}
    return None


def register(ctx):
    ctx.register_hook("pre_llm_call", rag_pre_llm_call)
