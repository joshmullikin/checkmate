"""Tests for api/routes/promote.py helpers and endpoints."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# Pure-helper tests (no HTTP needed)
# ──────────────────────────────────────────────────────────────────────────────

from api.routes.promote import _detect_vault_refs, _find_remote


def test_detect_vault_refs_single():
    steps = '[{"value": "{{myStore.password}}"}]'
    refs = _detect_vault_refs(steps)
    assert "{{myStore.password}}" in refs


def test_detect_vault_refs_multiple_deduped():
    steps = '[{"value": "{{store.username}}"}, {"value": "{{store.username}}"}]'
    refs = _detect_vault_refs(steps)
    assert refs.count("{{store.username}}") == 1


def test_detect_vault_refs_none():
    refs = _detect_vault_refs('[{"action": "navigate", "value": "/login"}]')
    assert refs == []


def test_find_remote_hit_and_miss(monkeypatch):
    remotes = [{"name": "staging", "url": "https://staging.example.com"}]
    monkeypatch.setattr("api.routes.promote.CHECKMATE_REMOTES", remotes)

    assert _find_remote("staging") == remotes[0]
    assert _find_remote("production") is None


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint tests
# ──────────────────────────────────────────────────────────────────────────────

def test_list_remotes_empty(client, monkeypatch):
    monkeypatch.setattr("api.routes.promote.CHECKMATE_REMOTES", [])
    res = client.get("/api/config/remotes")
    assert res.status_code == 200
    assert res.json() == []


def test_list_remotes_populated(client, monkeypatch):
    monkeypatch.setattr(
        "api.routes.promote.CHECKMATE_REMOTES",
        [{"name": "staging", "url": "https://staging.example.com"}],
    )
    res = client.get("/api/config/remotes")
    assert res.status_code == 200
    assert res.json() == [{"name": "staging"}]


def test_list_remote_projects_unknown_remote(client, monkeypatch):
    monkeypatch.setattr("api.routes.promote.CHECKMATE_REMOTES", [])
    res = client.get("/api/config/remotes/nonexistent/projects")
    assert res.status_code == 400


def test_list_remote_projects_connect_error(client, monkeypatch):
    import httpx
    monkeypatch.setattr(
        "api.routes.promote.CHECKMATE_REMOTES",
        [{"name": "prod", "url": "https://prod.example.com"}],
    )

    async def _raise_connect(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("httpx.AsyncClient.get", _raise_connect)

    res = client.get("/api/config/remotes/prod/projects")
    assert res.status_code == 502


def test_list_remote_projects_timeout(client, monkeypatch):
    import httpx
    monkeypatch.setattr(
        "api.routes.promote.CHECKMATE_REMOTES",
        [{"name": "prod", "url": "https://prod.example.com"}],
    )

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, *a, **kw):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeClient())

    res = client.get("/api/config/remotes/prod/projects")
    assert res.status_code == 504


def test_list_remote_projects_http_status_error(client, monkeypatch):
    import httpx
    monkeypatch.setattr(
        "api.routes.promote.CHECKMATE_REMOTES",
        [{"name": "prod", "url": "https://prod.example.com"}],
    )

    class _FakeResp:
        status_code = 403
        def raise_for_status(self):
            raise httpx.HTTPStatusError("forbidden", request=MagicMock(), response=self)
        def json(self): return []

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, *a, **kw): return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeClient())

    res = client.get("/api/config/remotes/prod/projects")
    assert res.status_code == 502


def test_list_remote_projects_success(client, monkeypatch):
    import httpx
    monkeypatch.setattr(
        "api.routes.promote.CHECKMATE_REMOTES",
        [{"name": "prod", "url": "https://prod.example.com"}],
    )

    class _FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return [{"id": 1, "name": "Prod Project", "base_url": "https://app.example.com"}]

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, *a, **kw): return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeClient())

    res = client.get("/api/config/remotes/prod/projects")
    assert res.status_code == 200
    assert res.json()[0]["name"] == "Prod Project"


def test_promote_unknown_remote(client, monkeypatch):
    monkeypatch.setattr("api.routes.promote.CHECKMATE_REMOTES", [])
    pid = client.post(
        "/api/projects",
        json={"name": "P", "description": "", "base_url": "https://example.com",
              "config": "{}", "base_prompt": "", "page_load_state": "load"},
    ).json()["id"]

    res = client.post(
        "/api/test-cases/promote",
        json={"test_case_ids": [1], "project_id": pid, "remote_name": "doesnotexist"},
    )
    assert res.status_code == 400


def test_promote_project_not_found(client, monkeypatch):
    monkeypatch.setattr(
        "api.routes.promote.CHECKMATE_REMOTES",
        [{"name": "staging", "url": "https://staging.example.com"}],
    )
    res = client.post(
        "/api/test-cases/promote",
        json={"test_case_ids": [1], "project_id": 9999999, "remote_name": "staging"},
    )
    assert res.status_code == 404


def test_promote_no_valid_test_cases(client, monkeypatch):
    monkeypatch.setattr(
        "api.routes.promote.CHECKMATE_REMOTES",
        [{"name": "staging", "url": "https://staging.example.com"}],
    )
    pid = client.post(
        "/api/projects",
        json={"name": "Promote P", "description": "", "base_url": "https://example.com",
              "config": "{}", "base_prompt": "", "page_load_state": "load"},
    ).json()["id"]

    res = client.post(
        "/api/test-cases/promote",
        json={"test_case_ids": [99999], "project_id": pid, "remote_name": "staging"},
    )
    assert res.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# Vault reference warnings during promote
# ──────────────────────────────────────────────────────────────────────────────

def _make_project(client, name="Test Project"):
    res = client.post(
        "/api/projects",
        json={
            "name": name,
            "description": "",
            "base_url": "https://example.com",
            "config": "{}",
            "base_prompt": "",
            "page_load_state": "load",
        },
    )
    assert res.status_code == 200
    return res.json()


def _make_test_case(client, project_id, name, steps=None):
    if steps is None:
        steps = '[{"action": "navigate", "value": "/"}]'
    res = client.post(
        "/api/test-cases",
        json={
            "project_id": project_id,
            "name": name,
            "description": "Test",
            "natural_query": "Test query",
            "steps": steps,
            "expected_result": "Success",
            "tags": "[]",
            "priority": "medium",
            "status": "draft",
        },
    )
    assert res.status_code == 200
    return res.json()


def test_promote_vault_references_add_warning(client, monkeypatch):
    """Promote adds warning when test case steps contain vault references."""
    project = _make_project(client)
    tc = _make_test_case(
        client,
        project["id"],
        name="Vault Login",
        steps=json.dumps([
            {"action": "fill", "target": "email", "value": "{{admin_creds.username}}"},
            {"action": "fill", "target": "password", "value": "{{admin_creds.password}}"},
        ]),
    )

    monkeypatch.setattr(
        "api.routes.promote.CHECKMATE_REMOTES",
        [{"name": "staging", "url": "https://staging.example.com"}],
    )

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "test_cases_created": 1,
                "test_cases_skipped": 0,
                "fixtures_created": 0,
                "fixtures_reused": 0,
                "warnings": [],
            }

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: FakeClient())

    res = client.post(
        "/api/test-cases/promote",
        json={
            "test_case_ids": [tc["id"]],
            "project_id": project["id"],
            "remote_name": "staging",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert any("vault entries" in w.lower() for w in data["warnings"])


def test_promote_no_vault_refs_no_warning(client, monkeypatch):
    """Promote does NOT add vault warning when steps have no vault references."""
    project = _make_project(client)
    tc = _make_test_case(
        client,
        project["id"],
        name="Simple Nav",
        steps=json.dumps([{"action": "navigate", "value": "/login"}]),
    )

    monkeypatch.setattr(
        "api.routes.promote.CHECKMATE_REMOTES",
        [{"name": "staging", "url": "https://staging.example.com"}],
    )

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "test_cases_created": 1,
                "test_cases_skipped": 0,
                "fixtures_created": 0,
                "fixtures_reused": 0,
                "warnings": [],
            }

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: FakeClient())

    res = client.post(
        "/api/test-cases/promote",
        json={
            "test_case_ids": [tc["id"]],
            "project_id": project["id"],
            "remote_name": "staging",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert all("vault entries" not in w.lower() for w in data["warnings"])


