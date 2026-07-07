import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins-source" / "hermes-brain-rag"
PLUGIN_INIT = PLUGIN_DIR / "__init__.py"
PLUGIN_YAML = PLUGIN_DIR / "plugin.yaml"
PACKAGED_PLUGIN_DIR = REPO_ROOT / "rag" / "obsidian-rag" / "plugins" / "hermes-brain-rag"
PACKAGED_PLUGIN_INIT = PACKAGED_PLUGIN_DIR / "__init__.py"
PACKAGED_PLUGIN_YAML = PACKAGED_PLUGIN_DIR / "plugin.yaml"


@pytest.fixture(autouse=True)
def isolate_plugin_env(monkeypatch):
    for key in (
        "AILAB_FOUNDATION_URL",
        "AILAB_FOUNDATION_API_KEY",
        "AILAB_BRAIN_FIRST",
        "AILAB_ALLOW_WEB_DEFAULT",
        "AILAB_DOMAIN_HINTS",
        "AILAB_FOUNDATION_ENV_FILE",
        "HERMES_BRAIN_RAG_CONTEXT_URL",
        "HERMES_BRAIN_RAG_FOUNDATION_URL",
        "HERMES_BRAIN_RAG_TIMEOUT",
        "HERMES_BRAIN_RAG_ENABLED",
        "HERMES_BRAIN_RAG_API_KEY",
        "HERMES_BRAIN_RAG_ENV_FILE",
        "API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def _load_plugin():
    spec = importlib.util.spec_from_file_location("hermes_brain_rag_plugin", PLUGIN_INIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _foundation_response(*, brain_status="sufficient", web_status="not_needed", blocks=None, citations=None):
    return {
        "answer_mode": "context_only",
        "brain_status": brain_status,
        "web_status": web_status,
        "confidence": "high" if brain_status == "sufficient" else "low",
        "context_blocks": blocks if blocks is not None else [
            {
                "block_id": "brain-block-1",
                "origin": "brain",
                "role": "definition",
                "text": "Foundation says adapters must preserve durable evidence refs.",
                "source_refs": ["vault://Architecture/Adapter Pattern.md#AI Context"],
                "evidence_refs": ["evidence:adapter-note#ai-context"],
                "citations": ["vault://Architecture/Adapter Pattern.md#AI Context"],
                "artifact_ref": "artifact:adapter-note",
            }
        ],
        "citations": citations if citations is not None else [
            {
                "origin": "brain",
                "source_ref": "vault://Architecture/Adapter Pattern.md#AI Context",
                "source_type": "citation",
                "block_ids": ["brain-block-1"],
            }
        ],
        "diagnostics": [],
    }


def _fake_response(payload):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(payload).encode()

    return FakeResponse()


def test_source_controlled_plugin_artifact_is_installable():
    assert PLUGIN_INIT.exists(), "source-controlled plugin __init__.py is missing"
    assert PLUGIN_INIT.stat().st_size > 0, "source-controlled plugin __init__.py is empty"
    assert PLUGIN_YAML.exists(), "source-controlled plugin plugin.yaml is missing"
    yaml_text = PLUGIN_YAML.read_text()
    assert "name: hermes-brain-rag" in yaml_text
    assert "pre_llm_call" in yaml_text

    plugin = _load_plugin()
    assert callable(plugin.register)

    registered = []

    class FakeContext:
        def register_hook(self, name, callback):
            registered.append((name, callback))

    plugin.register(FakeContext())

    assert registered
    assert registered[0][0] == "pre_llm_call"
    assert callable(registered[0][1])


def test_packaged_plugin_copy_stays_in_sync_with_source_artifact():
    assert PACKAGED_PLUGIN_INIT.exists(), "packaged plugin __init__.py is missing"
    assert PACKAGED_PLUGIN_YAML.exists(), "packaged plugin plugin.yaml is missing"
    assert PACKAGED_PLUGIN_INIT.read_text() == PLUGIN_INIT.read_text()
    assert PACKAGED_PLUGIN_YAML.read_text() == PLUGIN_YAML.read_text()


def test_pre_llm_hook_posts_foundation_answers_request_and_returns_cited_context(monkeypatch):
    plugin = _load_plugin()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode())
        return _fake_response(_foundation_response())

    monkeypatch.setenv("AILAB_FOUNDATION_API_KEY", "test-key")
    monkeypatch.setenv("AILAB_FOUNDATION_URL", "http://ai-lab-foundation-api:8088")
    monkeypatch.setenv("AILAB_DOMAIN_HINTS", "software_engineering, personal_knowledge")
    monkeypatch.setenv("HERMES_BRAIN_RAG_TIMEOUT", "1.25")
    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(
        session_id="session-1",
        user_message="what do you know about adapter evidence",
        platform="telegram",
        model="test-model",
    )

    assert captured["url"] == "http://ai-lab-foundation-api:8088/answers"
    assert captured["timeout"] == 1.25
    assert captured["body"] == {
        "query": "what do you know about adapter evidence",
        "mode": "context_only",
        "brain_first": True,
        "allow_web": False,
        "domain_hints": ["software_engineering", "personal_knowledge"],
        "include_diagnostics": True,
    }
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["headers"]["X-api-key"] == "test-key"

    assert result is not None
    context = result["context"]
    assert context.startswith("## Hermes Brain retrieved context")
    assert "Brain status: sufficient" in context
    assert "Web status: not_needed" in context
    assert "Foundation says adapters must preserve durable evidence refs." in context
    assert "### Citations" in context
    assert "vault://Architecture/Adapter Pattern.md#AI Context" in context
    assert "When answering from this context, cite the source_ref labels" in context


def test_pre_llm_hook_reads_foundation_api_key_from_project_env_file(monkeypatch, tmp_path):
    plugin = _load_plugin()
    captured = {}
    env_file = tmp_path / "foundation.env"
    env_file.write_text("AILAB_FOUNDATION_API_KEY=file-key\n", encoding="utf-8")

    def fake_urlopen(req, timeout):
        captured["headers"] = dict(req.header_items())
        return _fake_response(_foundation_response())

    monkeypatch.delenv("AILAB_FOUNDATION_API_KEY", raising=False)
    monkeypatch.delenv("HERMES_BRAIN_RAG_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("HERMES_BRAIN_RAG_ENV_FILE", str(env_file))
    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(user_message="adapter evidence")

    assert result is not None
    assert captured["headers"]["Authorization"] == "Bearer file-key"
    assert captured["headers"]["X-api-key"] == "file-key"


def test_pre_llm_hook_labels_brain_unavailable_when_foundation_cannot_be_reached(monkeypatch):
    plugin = _load_plugin()
    captured = {}

    def broken_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode())
        raise OSError("connection refused")

    monkeypatch.setenv("AILAB_FOUNDATION_API_KEY", "test-key")
    monkeypatch.setattr(plugin.request, "urlopen", broken_urlopen)

    result = plugin.inject_hermes_brain_context(user_message="linear regression")

    assert captured["body"]["allow_web"] is False
    assert result is not None
    context = result["context"]
    assert "Brain status: unavailable" in context
    assert "Foundation /answers unavailable" in context
    assert "Do not silently fall back to web" in context


def test_pre_llm_hook_makes_insufficient_brain_evidence_explicit_without_default_web(monkeypatch):
    plugin = _load_plugin()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode())
        return _fake_response(_foundation_response(brain_status="insufficient", web_status="not_allowed", blocks=[], citations=[]))

    monkeypatch.setenv("AILAB_ALLOW_WEB_DEFAULT", "false")
    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(user_message="missing brain topic")

    assert captured["body"]["allow_web"] is False
    assert result is not None
    context = result["context"]
    assert "Brain status: insufficient" in context
    assert "Web status: not_allowed" in context
    assert "Brain evidence is insufficient" in context
    assert "Do not use web evidence unless the user explicitly requested web" in context


def test_pre_llm_hook_allows_web_only_when_user_explicitly_requests_web(monkeypatch):
    plugin = _load_plugin()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode())
        return _fake_response(
            _foundation_response(
                brain_status="insufficient",
                web_status="used",
                blocks=[
                    {
                        "block_id": "web-block-1",
                        "origin": "web",
                        "text": "Explicit web fallback found current public evidence.",
                        "source_refs": ["https://example.test/evidence"],
                    }
                ],
                citations=[
                    {
                        "origin": "web",
                        "source_ref": "https://example.test/evidence",
                        "block_ids": ["web-block-1"],
                    }
                ],
            )
        )

    monkeypatch.setenv("AILAB_ALLOW_WEB_DEFAULT", "false")
    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(
        user_message="Please search the web for the current adapter evidence status"
    )

    assert captured["body"]["allow_web"] is True
    assert result is not None
    context = result["context"]
    assert "Web status: used" in context
    assert "Explicit web fallback found current public evidence." in context
    assert "https://example.test/evidence" in context


def test_pre_llm_hook_does_not_enable_web_for_topical_web_words(monkeypatch):
    plugin = _load_plugin()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode())
        return _fake_response(_foundation_response(brain_status="insufficient", web_status="not_allowed", blocks=[], citations=[]))

    monkeypatch.setenv("AILAB_ALLOW_WEB_DEFAULT", "false")
    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(
        user_message="What do my brain notes say about Google and online algorithms?"
    )
    first_body = captured["body"]

    result_for_product_name = plugin.inject_hermes_brain_context(
        user_message="What do my notes say about Google for Startups?"
    )

    assert first_body["allow_web"] is False
    assert captured["body"]["allow_web"] is False
    assert result is not None
    assert result_for_product_name is not None
    assert "Do not use web evidence unless the user explicitly requested web" in result["context"]


def test_pre_llm_hook_renders_top_level_citations_even_when_block_refs_are_absent(monkeypatch):
    plugin = _load_plugin()

    def fake_urlopen(req, timeout):
        return _fake_response(
            _foundation_response(
                blocks=[
                    {
                        "block_id": "brain-block-with-top-level-citation",
                        "origin": "brain",
                        "role": "definition",
                        "text": "Context text relies on top-level citation metadata.",
                    }
                ],
                citations=[
                    {
                        "origin": "brain",
                        "artifact_id": "artifact:top-level-citation",
                        "quote": "Top-level citation quote.",
                        "block_ids": ["brain-block-with-top-level-citation"],
                    }
                ],
            )
        )

    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(user_message="citation-only foundation context")

    assert result is not None
    context = result["context"]
    assert "Context text relies on top-level citation metadata." in context
    assert "### Citations" in context
    assert "artifact:top-level-citation" in context
    assert "brain-block-with-top-level-citation" in context


def test_pre_llm_hook_posts_to_mock_foundation_http_api(monkeypatch):
    plugin = _load_plugin()
    received = []

    class MockFoundationHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            received.append(
                {
                    "path": self.path,
                    "body": json.loads(self.rfile.read(length).decode()),
                }
            )
            raw = json.dumps(_foundation_response()).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), MockFoundationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("AILAB_FOUNDATION_URL", f"http://127.0.0.1:{server.server_port}")

        result = plugin.inject_hermes_brain_context(user_message="mock foundation http smoke")

        assert received
        assert received[0]["path"] == "/answers"
        assert received[0]["body"]["allow_web"] is False
        assert result is not None
        assert "vault://Architecture/Adapter Pattern.md#AI Context" in result["context"]
    finally:
        server.shutdown()
        server.server_close()


def test_pre_llm_hook_can_extract_latest_user_message_from_history(monkeypatch):
    plugin = _load_plugin()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode())
        return _fake_response(_foundation_response())

    monkeypatch.setenv("AILAB_FOUNDATION_API_KEY", "test-key")
    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(
        user_message=None,
        conversation_history=[
            {"role": "user", "content": "older question"},
            {"role": "assistant", "content": "older answer"},
            {"role": "user", "content": "latest adapter evidence question"},
        ],
    )

    assert captured["body"]["query"] == "latest adapter evidence question"
    assert result is not None
    assert "Brain status: sufficient" in result["context"]


def test_pre_llm_hook_can_be_disabled_by_brain_first_config(monkeypatch):
    plugin = _load_plugin()

    def unexpected_urlopen(req, timeout):  # pragma: no cover - must not be called
        raise AssertionError("Foundation should not be called when brain-first is disabled")

    monkeypatch.setenv("AILAB_BRAIN_FIRST", "false")
    monkeypatch.setattr(plugin.request, "urlopen", unexpected_urlopen)

    assert plugin.inject_hermes_brain_context(user_message="adapter evidence") is None
