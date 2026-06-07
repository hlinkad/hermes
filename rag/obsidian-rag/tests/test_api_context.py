from fastapi.testclient import TestClient

from deep_notes import api


def test_context_endpoint_returns_retrieval_context(monkeypatch):
    monkeypatch.setattr(api.settings, "api_key", "test-key")
    monkeypatch.setattr(api, "build_context_for_prompt", lambda prompt, settings: f"ctx:{prompt}")
    client = TestClient(api.app)

    response = client.post(
        "/api/context",
        json={"prompt": "Adapter design pattern"},
        headers={"Authorization": "Bearer test-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"context": "ctx:Adapter design pattern"}
