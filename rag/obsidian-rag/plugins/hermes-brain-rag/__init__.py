"""Hermes Brain RAG plugin.

Dependency-free pre-LLM hook that asks the local Hermes Brain RAG API for
retrieval context and injects it into the current turn. The heavy RAG stack
(LlamaIndex/Qdrant/etc.) stays outside the Hermes gateway process.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib import error, request

logger = logging.getLogger(__name__)

_DEFAULT_CONTEXT_URL = "http://127.0.0.1:8000/api/context"
_API_KEY_ENV_NAMES = ("HERMES_BRAIN_RAG_API_KEY", "API_KEY")


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _timeout_seconds() -> float:
    raw = os.getenv("HERMES_BRAIN_RAG_TIMEOUT", "2.5")
    try:
        return max(0.1, float(raw))
    except ValueError:
        logger.warning("Invalid HERMES_BRAIN_RAG_TIMEOUT=%r; using 2.5s", raw)
        return 2.5


def _candidate_env_files() -> list[Path]:
    """Return local env files that may hold the RAG API key.

    The gateway should normally receive HERMES_BRAIN_RAG_API_KEY from the
    Hermes environment. The RAG app also keeps the same key in its project-local
    deep_notes/.env, so use that as a fallback to keep gateway restarts from
    silently losing retrieval auth.
    """
    candidates: list[Path] = []
    explicit = os.getenv("HERMES_BRAIN_RAG_ENV_FILE")
    if explicit:
        candidates.append(Path(explicit).expanduser())

    home = Path.home()
    candidates.extend(
        [
            home / "hermes-infra/hermes-related-code/rag/obsidian-rag/deep_notes/.env",
            home / "workspace/hermes-related-code/rag/obsidian-rag/deep_notes/.env",
            Path("/workspace/hermes-related-code/rag/obsidian-rag/deep_notes/.env"),
        ]
    )
    return candidates


def _read_env_value(path: Path, names: tuple[str, ...]) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() not in names:
            continue
        return value.strip().strip('"').strip("'")
    return ""


def _api_key() -> str:
    for name in _API_KEY_ENV_NAMES:
        value = os.getenv(name)
        if value:
            return value

    for path in _candidate_env_files():
        value = _read_env_value(path, _API_KEY_ENV_NAMES)
        if value:
            return value
    return ""


def _message_get(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(key, default)
    return getattr(message, key, default)


def _content_to_text(content: Any) -> str:
    """Convert common OpenAI/Hermes content shapes into plain prompt text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content") or ""
                if isinstance(value, str):
                    parts.append(value)
        return "\n".join(part for part in parts if part)
    return "" if content is None else str(content)


def _latest_user_prompt(
    *,
    user_message: Any = None,
    conversation_history: list[Any] | None = None,
    messages: list[Any] | None = None,
) -> str:
    if user_message:
        return _content_to_text(user_message).strip()

    for message in reversed(conversation_history or messages or []):
        if _message_get(message, "role") == "user":
            return _content_to_text(_message_get(message, "content", "")).strip()

    return ""


def _extract_context(payload: Any) -> str:
    """Return context text from common API response shapes."""
    if isinstance(payload, str):
        return payload.strip()

    if not isinstance(payload, dict):
        return ""

    for key in ("context", "text", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    results = payload.get("results")
    if isinstance(results, list):
        parts: list[str] = []
        for item in results:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(
                    item.get("text")
                    or item.get("content")
                    or item.get("snippet")
                    or ""
                ).strip()
            else:
                text = ""
            if text:
                parts.append(text)
        return "\n\n".join(parts).strip()

    return ""


def _post_context_request(url: str, payload: dict[str, Any], timeout: float) -> str:
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    api_key = _api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key

    req = request.Request(url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")

    if not raw.strip():
        return ""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()

    return _extract_context(parsed)


def _context_payload(context: str) -> dict[str, str] | None:
    context = context.strip()
    if not context:
        return None

    lower = context.lower()
    if lower.startswith("## hermes brain retrieved context") or lower.startswith(
        "hermes brain retrieved context"
    ):
        return {"context": context}

    return {"context": f"Hermes Brain retrieved context:\n{context}"}


def inject_hermes_brain_context(
    session_id: str | None = None,
    user_message: Any = None,
    conversation_history: list[dict[str, Any]] | None = None,
    is_first_turn: bool = False,
    model: str | None = None,
    platform: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, str] | None:
    """pre_llm_call hook: return retrieved context or None.

    The hook intentionally fails closed: any API outage, timeout, or malformed
    response produces no injection rather than breaking the chat turn.
    """
    if not _env_bool("HERMES_BRAIN_RAG_ENABLED", True):
        return None

    prompt = _latest_user_prompt(
        user_message=user_message,
        conversation_history=conversation_history,
        messages=messages or kwargs.get("messages"),
    )
    if not prompt:
        return None

    url = os.getenv("HERMES_BRAIN_RAG_CONTEXT_URL", _DEFAULT_CONTEXT_URL).strip()
    if not url:
        return None

    payload: dict[str, Any] = {
        "prompt": prompt,
        "session_id": session_id,
        "platform": platform,
        "model": model,
        "is_first_turn": is_first_turn,
    }

    try:
        context = _post_context_request(url, payload, _timeout_seconds())
    except error.HTTPError as exc:
        logger.debug("Hermes Brain RAG context request failed: HTTP %s", exc.code)
        return None
    except Exception as exc:  # noqa: BLE001 - plugin must fail closed
        logger.debug("Hermes Brain RAG context request failed: %s", exc)
        return None

    return _context_payload(context)


def register(ctx: Any) -> None:
    """Register the pre-LLM context injection hook."""
    ctx.register_hook("pre_llm_call", inject_hermes_brain_context)
