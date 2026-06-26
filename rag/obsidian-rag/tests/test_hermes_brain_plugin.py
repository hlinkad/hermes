import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins-source" / "hermes-brain-rag"
PLUGIN_INIT = PLUGIN_DIR / "__init__.py"
PLUGIN_YAML = PLUGIN_DIR / "plugin.yaml"
PACKAGED_PLUGIN_DIR = REPO_ROOT / "rag" / "obsidian-rag" / "plugins" / "hermes-brain-rag"
PACKAGED_PLUGIN_INIT = PACKAGED_PLUGIN_DIR / "__init__.py"
PACKAGED_PLUGIN_YAML = PACKAGED_PLUGIN_DIR / "plugin.yaml"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("hermes_brain_rag_plugin", PLUGIN_INIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_pre_llm_hook_posts_prompt_and_returns_context(monkeypatch):
    plugin = _load_plugin()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"context": "retrieved linear regression context"}).encode()

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode())
        return FakeResponse()

    monkeypatch.setenv("HERMES_BRAIN_RAG_API_KEY", "test-key")
    monkeypatch.setenv("HERMES_BRAIN_RAG_CONTEXT_URL", "http://rag.local/api/context")
    monkeypatch.setenv("HERMES_BRAIN_RAG_TIMEOUT", "1.25")
    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(
        session_id="session-1",
        user_message="what do you know about linear regression",
        platform="telegram",
        model="test-model",
    )

    assert result == {
        "context": "Hermes Brain retrieved context:\nretrieved linear regression context"
    }
    assert captured["url"] == "http://rag.local/api/context"
    assert captured["timeout"] == 1.25
    assert captured["body"]["prompt"] == "what do you know about linear regression"
    assert captured["body"]["session_id"] == "session-1"
    assert captured["body"]["platform"] == "telegram"
    assert captured["body"]["model"] == "test-model"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["headers"]["X-api-key"] == "test-key"


def test_pre_llm_hook_reads_api_key_from_project_env_file(monkeypatch, tmp_path):
    plugin = _load_plugin()
    captured = {}
    env_file = tmp_path / "deep_notes.env"
    env_file.write_text("API_KEY=file-key\n", encoding="utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"context":"ctx from env-file auth"}'

    def fake_urlopen(req, timeout):
        captured["headers"] = dict(req.header_items())
        return FakeResponse()

    monkeypatch.delenv("HERMES_BRAIN_RAG_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("HERMES_BRAIN_RAG_ENV_FILE", str(env_file))
    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(user_message="linear regression")

    assert result == {"context": "Hermes Brain retrieved context:\nctx from env-file auth"}
    assert captured["headers"]["Authorization"] == "Bearer file-key"
    assert captured["headers"]["X-api-key"] == "file-key"


def test_pre_llm_hook_fails_closed_on_unavailable_context_api(monkeypatch):
    plugin = _load_plugin()

    def broken_urlopen(req, timeout):
        raise OSError("connection refused")

    monkeypatch.setenv("HERMES_BRAIN_RAG_API_KEY", "test-key")
    monkeypatch.setattr(plugin.request, "urlopen", broken_urlopen)

    assert plugin.inject_hermes_brain_context(user_message="linear regression") is None


def test_pre_llm_hook_can_extract_latest_user_message_from_history(monkeypatch):
    plugin = _load_plugin()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"context":"ctx from history"}'

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode())
        return FakeResponse()

    monkeypatch.setenv("HERMES_BRAIN_RAG_API_KEY", "test-key")
    monkeypatch.setattr(plugin.request, "urlopen", fake_urlopen)

    result = plugin.inject_hermes_brain_context(
        user_message=None,
        conversation_history=[
            {"role": "user", "content": "older question"},
            {"role": "assistant", "content": "older answer"},
            {"role": "user", "content": "latest linear regression question"},
        ],
    )

    assert captured["body"]["prompt"] == "latest linear regression question"
    assert result == {"context": "Hermes Brain retrieved context:\nctx from history"}
