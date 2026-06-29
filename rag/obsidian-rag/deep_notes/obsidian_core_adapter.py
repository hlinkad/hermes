"""Thin Hermes Brain consumer of obsidian-intelligence-core parser output.

This module is intentionally a boundary layer: the generic core parses Obsidian
Markdown and creates inert Hermes Brain metadata, while deep_notes keeps ownership
of source roots, source layers, LlamaIndex documents, Qdrant indexing, and
retrieval/citation behavior.
"""
from __future__ import annotations

import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from llama_index.core import Document

OBSIDIAN_STRUCTURAL_METADATA_KEYS = (
    "obsidian_metadata_schema",
    "frontmatter",
    "properties",
    "aliases",
    "cssclasses",
    "inline_tags",
    "headings",
    "links",
    "wikilinks",
    "embeds",
    "blocks",
    "block_ids",
    "callouts",
    "graph_edges",
    "canvas_refs",
    "canvas_references",
    "base_refs",
    "base_references",
    "diagnostics",
    "obsidian_summary",
)

_SENSITIVE_METADATA_KEY_TOKENS = {
    "jwt",
    "signature",
    "auth",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "password",
    "passwd",
    "secret",
    "token",
}
_SENSITIVE_METADATA_KEY_PHRASES = (
    ("api", "key"),
    ("api", "token"),
    ("x", "api", "key"),
    ("access", "key"),
    ("secret", "access", "key"),
    ("private", "key"),
    ("signing", "key"),
    ("access", "token"),
    ("refresh", "token"),
    ("id", "token"),
    ("bearer", "token"),
    ("basic", "auth"),
    ("client", "secret"),
    ("session", "id"),
    ("session", "token"),
)
_COMPACT_SENSITIVE_KEY_FRAGMENTS = (
    "apikey",
    "apitoken",
    "accesskey",
    "secretaccesskey",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "bearertoken",
    "clientsecret",
    "sessionid",
    "sessiontoken",
    "privatekey",
    "signingkey",
)
_UNSAFE_REQUEST_METADATA_KEYS = {
    "headers",
    "header",
    "request_headers",
    "request_header",
    "response_headers",
    "response_header",
    "http_headers",
    "http_header",
    "cookies",
    "set_cookie",
    "request",
    "response",
}
_AUTHORIZATION_VALUE_RE = re.compile(
    r"(?i)\b(authorization)(\s*[:=]\s*)(?:(?:bearer|basic|digest|token)\s+)?"
    r"(\"[^\"]*\"|'[^']*'|[^\s&#;,}}\]\[]+)"
    r"|\b(authorization)(\s+)(?:bearer|basic|digest|token)\s+"
    r"(\"[^\"]*\"|'[^']*'|[^\s&#;,}}\]\[]+)"
)
_METADATA_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9_.-]{0,100})(['\"]?\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s&#;,}}\]\[]+)"
)
_SPACED_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b("
    r"api\s+key|x\s+api\s+key|api\s+token|access\s+key|"
    r"secret\s+access\s+key|private\s+key|signing\s+key|"
    r"access\s+token|refresh\s+token|id\s+token|bearer\s+token|"
    r"client\s+secret|session\s+(?:id|token)|basic\s+auth"
    r")(\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s&#;,}}\]\[]+)"
)
_BEARER_SECRET_RE = re.compile(r"(?i)\b(bearer)\s+([^\s&#;,]+)")
_ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_OBSIDIAN_REFERENCE_RE = re.compile(r"(?P<embed>!)?\[\[(?P<body>[^\]\n]+)\]\]")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\([^)]*\)")
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[(?P<label>[^\]]+)\]\([^)]*\)")
_TRAILING_BLOCK_ID_RE = re.compile(r"(?<!\S)\^[A-Za-z0-9][A-Za-z0-9_-]*\s*$")
_CALLOUT_START_RE = re.compile(
    r"^\s*(?:>\s*)+\[![A-Za-z0-9_-]+\][+-]?(?:\s+(?P<title>.*))?$"
)
_BLOCKQUOTE_LINE_RE = re.compile(r"^\s*(?:>\s*)+(?P<content>.*)$")
_FENCE_LINE_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})")
_INLINE_WHITESPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"[ \t]+([,.;:!?])")

_CORE_SRC_CANDIDATES = (
    Path("/workspace/obsidian-intelligence-core/src"),
    Path("/Users/denishlinka/hermes-infra/obsidian-intelligence-core/src"),
)
_REQUIRED_CORE_FILES = (
    "obsidian_intelligence_core/__init__.py",
    "obsidian_intelligence_core/core/markdown.py",
    "obsidian_intelligence_core/adapters/hermes_brain/__init__.py",
)


def document_from_obsidian_core(
    path: Path,
    root: Path,
    *,
    source_kind: str,
    layer: str,
    obsidian_core_path: str = "",
) -> Document | None:
    """Parse one Markdown file with obsidian-intelligence-core and wrap it for RAG."""

    parse_markdown_file, document_to_payload = _load_core_adapter(obsidian_core_path)
    root = root.expanduser()
    relative_path = _relative_file_path(path, root)
    parsed_document = parse_markdown_file(path, vault_root=root)
    if not parsed_document.body.strip():
        return None

    payload = document_to_payload(
        parsed_document,
        source_root=str(root),
        source_kind=source_kind,
        layer=layer,
        file_path=relative_path,
    )
    return Document(
        text=_semantic_text_from_obsidian_body(payload.text),
        metadata=qdrant_safe_metadata(payload.metadata),
        excluded_embed_metadata_keys=list(OBSIDIAN_STRUCTURAL_METADATA_KEYS),
        excluded_llm_metadata_keys=list(OBSIDIAN_STRUCTURAL_METADATA_KEYS),
    )


def _semantic_text_from_obsidian_body(body: str) -> str:
    """Return source text suitable for embedding and answer context.

    The core parser intentionally preserves the original Markdown body. For RAG we
    keep user-authored prose, headings, and callout body text, but remove Obsidian
    reference syntax that is already represented in metadata payload fields.
    """

    lines: list[str] = []
    in_fence = False
    fence_marker = ""
    in_callout = False
    for raw_line in str(body or "").splitlines():
        fence = _FENCE_LINE_RE.match(raw_line)
        if fence:
            marker = fence.group("fence")
            marker_char = marker[0]
            if not in_fence:
                in_fence = True
                fence_marker = marker_char
            elif marker_char == fence_marker:
                in_fence = False
                fence_marker = ""
            lines.append(raw_line.rstrip())
            continue

        if in_fence:
            lines.append(raw_line.rstrip())
            continue

        line = raw_line
        callout = _CALLOUT_START_RE.match(line)
        if callout:
            in_callout = True
            line = callout.group("title") or ""
        elif in_callout:
            quoted = _BLOCKQUOTE_LINE_RE.match(line)
            if quoted:
                line = quoted.group("content")
            else:
                in_callout = False

        line = _OBSIDIAN_REFERENCE_RE.sub(_reference_text_replacement, line)
        line = _MARKDOWN_IMAGE_RE.sub(lambda match: match.group("alt").strip(), line)
        line = _MARKDOWN_LINK_RE.sub(lambda match: match.group("label").strip(), line)
        line = _TRAILING_BLOCK_ID_RE.sub("", line).rstrip()
        line = _normalize_inline_spacing(line).rstrip()

        if line.strip():
            lines.append(line)
        elif not raw_line.strip():
            lines.append("")

    return _collapse_blank_lines(lines).strip()


def _reference_text_replacement(match: re.Match[str]) -> str:
    if match.group("embed"):
        return ""

    body = match.group("body").strip()
    target, separator, alias = body.partition("|")
    if separator and alias.strip():
        return alias.strip()
    return _readable_reference_target(target)


def _readable_reference_target(target: str) -> str:
    text = target.strip()
    if not text or text.startswith("^"):
        return ""
    text = text.replace("#^", " ").replace("#", " ").replace("^", " ")
    if text.lower().endswith(".md"):
        text = text[:-3]
    return " ".join(part for part in text.split() if part)


def _collapse_blank_lines(lines: list[str]) -> str:
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = is_blank
    return "\n".join(collapsed)


def _normalize_inline_spacing(line: str) -> str:
    line = _INLINE_WHITESPACE_RE.sub(" ", line)
    return _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", line)


def qdrant_safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return JSON-compatible metadata safe to store in Qdrant payloads.

    Obsidian frontmatter/properties can contain arbitrary user-authored keys and
    copied request diagnostics. The live Qdrant collection is a derived cache, but
    it should still preserve only safe retrieval/debugging metadata: secret-shaped
    keys and HTTP request/response containers are omitted, while sensitive tokens in
    otherwise useful strings (for example source URLs) are redacted.
    """

    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        if not _is_safe_metadata_key(key_text):
            continue
        sanitized[key_text] = _sanitize_metadata_value(value)
    return sanitized


def _sanitize_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return qdrant_safe_metadata(value)
    if isinstance(value, tuple):
        return [_sanitize_metadata_value(item) for item in value]
    if isinstance(value, list):
        return [_sanitize_metadata_value(item) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    return value


def _is_safe_metadata_key(key: str) -> bool:
    canonical = _canonical_metadata_key(key)
    if not canonical:
        return False
    if (
        canonical in _UNSAFE_REQUEST_METADATA_KEYS
        or canonical.endswith("_headers")
        or canonical.endswith("_header")
    ):
        return False
    return not _is_sensitive_metadata_key(canonical)


def _canonical_metadata_key(key: str) -> str:
    decoded = unquote(str(key))
    decoded = _ACRONYM_BOUNDARY_RE.sub("_", decoded)
    decoded = _CAMEL_BOUNDARY_RE.sub("_", decoded)
    normalized = _NON_ALNUM_RE.sub("_", decoded.lower())
    return normalized.strip("_")


def _is_sensitive_metadata_key(canonical_key: str) -> bool:
    compact_key = canonical_key.replace("_", "")
    if any(fragment in compact_key for fragment in _COMPACT_SENSITIVE_KEY_FRAGMENTS):
        return True

    tokens = [token for token in canonical_key.split("_") if token]
    if canonical_key == "apikey" or any(
        token in _SENSITIVE_METADATA_KEY_TOKENS for token in tokens
    ):
        return True
    return any(
        _contains_token_phrase(tokens, phrase)
        for phrase in _SENSITIVE_METADATA_KEY_PHRASES
    )


def _contains_token_phrase(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    if len(tokens) < len(phrase):
        return False
    last_start = len(tokens) - len(phrase) + 1
    return any(
        tuple(tokens[start : start + len(phrase)]) == phrase
        for start in range(last_start)
    )


def _redact_authorization_value(match: re.Match[str]) -> str:
    key = match.group(1) or match.group(4)
    separator = match.group(2) or match.group(5)
    return f"{key}{separator}[redacted]"


def _redact_sensitive_assignment(match: re.Match[str]) -> str:
    key = match.group(1).strip(" '\"")
    if _is_sensitive_metadata_key(_canonical_metadata_key(key)):
        return f"{match.group(1)}{match.group(2)}[redacted]"
    return match.group(0)


def _redact_spaced_sensitive_assignment(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}[redacted]"


def _redact_sensitive_text(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""

    if "://" in text:
        scheme, remainder = text.split("://", 1)
        authority, separator, tail = remainder.partition("/")
        if "@" in authority:
            authority = "[redacted]@" + authority.rsplit("@", 1)[1]
        text = f"{scheme}://{authority}{separator}{tail}"

    prefix, question, query_and_fragment = text.partition("?")
    if question:
        query, fragment_separator, fragment = query_and_fragment.partition("#")
        redacted_query = _redact_parameter_segment(query)
        redacted_fragment = _redact_parameter_segment(fragment)
        text = f"{prefix}?{redacted_query}{fragment_separator}{redacted_fragment}"
    else:
        prefix, fragment_separator, fragment = text.partition("#")
        if fragment_separator:
            text = f"{prefix}#{_redact_parameter_segment(fragment)}"

    text = _AUTHORIZATION_VALUE_RE.sub(_redact_authorization_value, text)
    text = _BEARER_SECRET_RE.sub(lambda match: f"{match.group(1)} [redacted]", text)
    text = _SPACED_SENSITIVE_ASSIGNMENT_RE.sub(
        _redact_spaced_sensitive_assignment,
        text,
    )
    return _METADATA_ASSIGNMENT_RE.sub(_redact_sensitive_assignment, text)


def _redact_parameter_segment(segment: str) -> str:
    if not segment:
        return segment
    redacted_params: list[str] = []
    for param in segment.split("&"):
        name, equals, raw_value = param.partition("=")
        if _is_sensitive_metadata_key(_canonical_metadata_key(name)):
            if equals:
                redacted_params.append(f"{name}{equals}[redacted]")
            else:
                redacted_params.append(f"{name}=[redacted]")
        else:
            redacted_params.append(f"{name}{equals}{raw_value}")
    return "&".join(redacted_params)


def _load_core_adapter(obsidian_core_path: str) -> tuple[Callable, Callable]:
    core_src_path = _ensure_core_path(obsidian_core_path)
    try:
        from obsidian_intelligence_core.adapters.hermes_brain import (  # type: ignore[import-not-found]
            document_to_hermes_brain_rag_payload,
        )
        from obsidian_intelligence_core.core.markdown import (  # type: ignore[import-not-found]
            parse_markdown_file,
        )
    except ImportError as exc:  # pragma: no cover - exercised through RuntimeError path
        raise RuntimeError(
            "obsidian-intelligence-core is required when OBSIDIAN_CORE_ENABLED=true. "
            "Install it in the active RAG environment or set OBSIDIAN_CORE_PATH to the "
            "core repo root or src/ checkout; do not create/install a new venv without "
            "approval."
        ) from exc

    if core_src_path is not None:
        _assert_callable_loaded_from_core_path(parse_markdown_file, core_src_path)
        _assert_callable_loaded_from_core_path(
            document_to_hermes_brain_rag_payload,
            core_src_path,
        )
    return parse_markdown_file, document_to_hermes_brain_rag_payload


def _ensure_core_path(obsidian_core_path: str) -> Path | None:
    explicit_path = obsidian_core_path.strip()
    if explicit_path:
        path = _validated_core_src_path(Path(explicit_path).expanduser())
        _prepend_sys_path(path)
        return path

    try:
        import obsidian_intelligence_core  # noqa: F401  # type: ignore[import-not-found]
        return None
    except ImportError:
        pass

    for candidate in _CORE_SRC_CANDIDATES:
        if candidate.is_dir() and _has_required_core_files(candidate):
            _prepend_sys_path(candidate)
            return candidate.resolve()
    return None


def _validated_core_src_path(path: Path) -> Path:
    """Return a safe core src path or fail before Python import resolution.

    Explicit OBSIDIAN_CORE_PATH should not silently fall through to another installed
    package or auto-detected checkout. Accept either the core repo root or its src/
    directory, but require the expected package directory to exist there.
    """

    if not path.is_dir():
        raise RuntimeError(
            f"obsidian-intelligence-core path does not exist: {path}. "
            "Set OBSIDIAN_CORE_PATH to the core repo root or src/ directory."
        )

    if _has_required_core_files(path):
        return path.resolve()

    repo_src = path / "src"
    if _has_required_core_files(repo_src):
        return repo_src.resolve()

    raise RuntimeError(
        f"obsidian-intelligence-core path does not contain required core modules: {path}. "
        "Set OBSIDIAN_CORE_PATH to the core repo root or src/ directory."
    )


def _has_required_core_files(path: Path) -> bool:
    return all((path / relative_file).is_file() for relative_file in _REQUIRED_CORE_FILES)


def _assert_callable_loaded_from_core_path(func: Callable, core_src_path: Path) -> None:
    module_name = getattr(func, "__module__", "")
    module = sys.modules.get(module_name)
    origin = getattr(module, "__file__", "") if module is not None else ""
    if not origin:
        raise RuntimeError(
            "obsidian-intelligence-core import origin could not be verified for "
            f"{module_name or func!r}."
        )

    origin_path = Path(origin).resolve()
    core_root = core_src_path.resolve()
    try:
        origin_path.relative_to(core_root)
    except ValueError as exc:
        raise RuntimeError(
            "obsidian-intelligence-core import resolved outside OBSIDIAN_CORE_PATH: "
            f"{origin_path} is not under {core_root}. Restart the process or unset "
            "the conflicting package before enabling OBSIDIAN_CORE_PATH."
        ) from exc


def _prepend_sys_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def _relative_file_path(path: Path, root: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(root.expanduser().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
