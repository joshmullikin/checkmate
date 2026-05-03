"""Tests for /api/test-cases/import endpoint: auth, fixture dedup, test case dedup, and project targeting.

Uses the `client` fixture from conftest.py for proper test database isolation.
"""

import json
import pytest
from unittest.mock import MagicMock
from db import crud


# ──────────────────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────────────────

def _project(client, name="Test Project"):
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


def _test_case(client, project_id, name, steps=None):
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


# ──────────────────────────────────────────────────────────────────────────────
# Authentication tests for /test-cases/import
# ──────────────────────────────────────────────────────────────────────────────

def test_import_auth_missing_key_rejected(client, monkeypatch):
    """Import endpoint rejects request when API key is configured but missing from request."""
    monkeypatch.setattr("api.routes.promote.CHECKMATE_API_KEY", "secret-key-123")

    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Test",
            "project_base_url": "https://example.com",
            "test_cases": [],
            "fixtures": [],
        },
    )
    assert res.status_code == 401
    assert "Invalid or missing API key" in res.json()["detail"]


def test_import_auth_wrong_key_rejected(client, monkeypatch):
    """Import endpoint rejects request with wrong API key."""
    monkeypatch.setattr("api.routes.promote.CHECKMATE_API_KEY", "correct-key")

    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Test",
            "project_base_url": "https://example.com",
            "test_cases": [],
            "fixtures": [],
        },
        headers={"X-API-Key": "wrong-key"},
    )
    assert res.status_code == 401


def test_import_auth_disabled_no_key_needed(client, monkeypatch):
    """Import endpoint accepts request when no API key is configured."""
    monkeypatch.setattr("api.routes.promote.CHECKMATE_API_KEY", None)

    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Import Test",
            "project_base_url": "https://example.com",
            "test_cases": [],
            "fixtures": [],
        },
    )
    assert res.status_code == 200


def test_import_auth_correct_key_accepted(client, monkeypatch):
    """Import endpoint accepts request with correct API key."""
    monkeypatch.setattr("api.routes.promote.CHECKMATE_API_KEY", "correct-key-123")

    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Import Test",
            "project_base_url": "https://example.com",
            "test_cases": [],
            "fixtures": [],
        },
        headers={"X-API-Key": "correct-key-123"},
    )
    assert res.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# Fixture deduplication in import
# ──────────────────────────────────────────────────────────────────────────────

def test_import_fixture_dedup_reuses_existing(client):
    """Import reuses existing fixture when same name already exists in project."""
    project = _project(client, name="Dedup Project")
    pid = project["id"]

    # Create existing fixture
    fix_res = client.post(
        f"/api/projects/{pid}/fixtures",
        json={
            "name": "Shared Fixture",
            "description": "Original",
            "setup_steps": [{"action": "navigate", "value": "/setup"}],
            "scope": "cached",
            "cache_ttl_seconds": 3600,
        },
    )
    assert fix_res.status_code == 200

    # Import fixture with same name
    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Dedup Project",
            "project_base_url": "https://example.com",
            "target_project_id": pid,
            "fixtures": [
                {
                    "name": "Shared Fixture",
                    "description": "Imported (should be ignored)",
                    "setup_steps": '[{"action": "navigate"}]',
                    "scope": "cached",
                    "cache_ttl_seconds": 7200,
                }
            ],
            "test_cases": [],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["fixtures_reused"] == 1
    assert data["fixtures_created"] == 0


def test_import_fixture_creates_when_name_unique(client):
    """Import creates new fixture when name does not exist in project."""
    project = _project(client, name="New Fixture Project")
    pid = project["id"]

    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "New Fixture Project",
            "project_base_url": "https://example.com",
            "target_project_id": pid,
            "fixtures": [
                {
                    "name": "Brand New Fixture",
                    "description": "New",
                    "setup_steps": '[{"action": "navigate"}]',
                    "scope": "test",
                    "cache_ttl_seconds": 300,
                }
            ],
            "test_cases": [],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["fixtures_created"] == 1
    assert data["fixtures_reused"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Test case deduplication
# ──────────────────────────────────────────────────────────────────────────────

def test_import_skips_existing_test_case(client):
    """Import skips test case with name already in project."""
    project = _project(client, name="Skip Test")
    pid = project["id"]

    # Create existing test case
    _test_case(client, pid, "Existing Test")

    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Skip Test",
            "project_base_url": "https://example.com",
            "target_project_id": pid,
            "fixtures": [],
            "test_cases": [
                {
                    "name": "Existing Test",
                    "description": "Duplicate",
                    "natural_query": "Q",
                    "steps": "[]",
                    "fixture_names": [],
                    "priority": "medium",
                    "status": "draft",
                }
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["test_cases_skipped"] == 1
    assert data["test_cases_created"] == 0


def test_import_creates_unique_test_case(client):
    """Import creates test case when name doesn't exist in project."""
    project = _project(client, name="Create Test")
    pid = project["id"]

    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Create Test",
            "project_base_url": "https://example.com",
            "target_project_id": pid,
            "fixtures": [],
            "test_cases": [
                {
                    "name": "Unique New Test",
                    "description": "New",
                    "natural_query": "Q",
                    "steps": "[]",
                    "fixture_names": [],
                    "priority": "high",
                    "status": "active",
                }
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["test_cases_created"] == 1
    assert data["test_cases_skipped"] == 0


def test_import_mixed_skip_and_create(client):
    """Import correctly handles mix of existing and new test cases."""
    project = _project(client, name="Mixed Import")
    pid = project["id"]

    # Create one existing test case
    _test_case(client, pid, "Already Exists")

    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Mixed Import",
            "project_base_url": "https://example.com",
            "target_project_id": pid,
            "fixtures": [],
            "test_cases": [
                {
                    "name": "Already Exists",
                    "description": "Skip this",
                    "natural_query": "Q",
                    "steps": "[]",
                    "fixture_names": [],
                    "priority": "medium",
                    "status": "draft",
                },
                {
                    "name": "New One",
                    "description": "Create this",
                    "natural_query": "Q",
                    "steps": "[]",
                    "fixture_names": [],
                    "priority": "high",
                    "status": "draft",
                },
                {
                    "name": "Another New One",
                    "description": "Create this too",
                    "natural_query": "Q",
                    "steps": "[]",
                    "fixture_names": [],
                    "priority": "low",
                    "status": "draft",
                },
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["test_cases_skipped"] == 1
    assert data["test_cases_created"] == 2


# ──────────────────────────────────────────────────────────────────────────────
# target_project_id handling
# ──────────────────────────────────────────────────────────────────────────────

def test_import_uses_target_project_id(client):
    """Import places test cases in specified target_project_id."""
    project1 = _project(client, name="Source Project")
    project2 = _project(client, name="Target Project")

    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Source Project",
            "project_base_url": "https://source.example.com",
            "target_project_id": project2["id"],
            "fixtures": [],
            "test_cases": [
                {
                    "name": "Goes To Project2",
                    "description": "Should go to project 2",
                    "natural_query": "Q",
                    "steps": "[]",
                    "fixture_names": [],
                    "priority": "medium",
                    "status": "draft",
                }
            ],
        },
    )
    assert res.status_code == 200

    # Verify test case is in project2
    tcs_res = client.get(f"/api/test-cases/project/{project2['id']}")
    assert tcs_res.status_code == 200
    tcs = tcs_res.json()
    assert any(tc["name"] == "Goes To Project2" for tc in tcs)


def test_import_target_project_not_found(client):
    """Import returns 404 when target_project_id doesn't exist."""
    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Test",
            "project_base_url": "https://example.com",
            "target_project_id": 9999999,
            "fixtures": [],
            "test_cases": [],
        },
    )
    assert res.status_code == 404


def test_import_creates_new_project_when_target_none(client):
    """Import creates new project when target_project_id is absent."""
    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Auto Created Project Wave8",
            "project_base_url": "https://auto.example.com",
            "project_description": "Created by import",
            "fixtures": [],
            "test_cases": [
                {
                    "name": "Auto TC",
                    "description": "Test",
                    "natural_query": "Q",
                    "steps": "[]",
                    "fixture_names": [],
                    "priority": "medium",
                    "status": "draft",
                }
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    # Should have warning about creating new project
    assert any("Created new project" in w for w in data["warnings"])
    assert data["test_cases_created"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# Fixture name to ID remapping in test case creation
# ──────────────────────────────────────────────────────────────────────────────

def test_import_remaps_fixture_names_to_ids(client):
    """Import correctly maps fixture names to fixture IDs in created test case."""
    project = _project(client, name="Fixture Remap")
    pid = project["id"]

    # Create a fixture in the project
    fix_res = client.post(
        f"/api/projects/{pid}/fixtures",
        json={
            "name": "Setup Fixture",
            "description": "Setup",
            "setup_steps": [{"action": "navigate"}],
            "scope": "cached",
        },
    )
    fix_id = fix_res.json()["id"]

    # Import test case that references the fixture by name
    res = client.post(
        "/api/test-cases/import",
        json={
            "project_name": "Fixture Remap",
            "project_base_url": "https://example.com",
            "target_project_id": pid,
            "fixtures": [],  # Fixture already exists
            "test_cases": [
                {
                    "name": "TC with Fixture",
                    "description": "Uses fixture",
                    "natural_query": "Q",
                    "steps": "[]",
                    "fixture_names": ["Setup Fixture"],
                    "priority": "high",
                    "status": "active",
                }
            ],
        },
    )
    assert res.status_code == 200

    # Verify test case has correct fixture ID
    tcs_res = client.get(f"/api/test-cases/project/{pid}")
    assert tcs_res.status_code == 200
    tcs = tcs_res.json()
    created_tc = next((tc for tc in tcs if tc["name"] == "TC with Fixture"), None)
    assert created_tc is not None
    # fixture_ids is stored as a JSON string like "[3, 7]"
    fixture_ids_raw = created_tc.get("fixture_ids")
    if fixture_ids_raw is not None:
        parsed_ids = json.loads(fixture_ids_raw)
        assert fix_id in parsed_ids
