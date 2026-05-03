from fastapi.testclient import TestClient

import api.main as main_module
import api.routes.config as config_routes


def test_features_endpoint_with_no_remotes(monkeypatch):
    monkeypatch.setattr(config_routes, "INTELLIGENT_RETRY_ENABLED", True)
    monkeypatch.setattr(config_routes, "MULTIPLE_ENVIRONMENTS", False)
    monkeypatch.setattr(config_routes, "CHECKMATE_REMOTES", [])

    client = TestClient(main_module.app)
    response = client.get("/api/features")

    assert response.status_code == 200
    assert response.json() == {
        "intelligent_retry": True,
        "multiple_environments": False,
        "remotes_configured": False,
    }


def test_features_endpoint_with_remotes_configured(monkeypatch):
    monkeypatch.setattr(config_routes, "INTELLIGENT_RETRY_ENABLED", False)
    monkeypatch.setattr(config_routes, "MULTIPLE_ENVIRONMENTS", True)
    monkeypatch.setattr(config_routes, "CHECKMATE_REMOTES", [
        {"name": "remote-1", "url": "https://example.com"}
    ])

    client = TestClient(main_module.app)
    response = client.get("/api/features")

    assert response.status_code == 200
    assert response.json() == {
        "intelligent_retry": False,
        "multiple_environments": True,
        "remotes_configured": True,
    }
