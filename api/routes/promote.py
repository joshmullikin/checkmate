"""Test case promotion across remote Checkmate environments."""

import json
import re
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from core.config import CHECKMATE_REMOTES, CHECKMATE_API_KEY
from core.logging import get_logger
from db import crud
from db.models import (
    TestCaseCreate,
    FixtureCreate,
    ProjectCreate,
)
from db.session import get_session_dep

logger = get_logger(__name__)

router = APIRouter(tags=["promote"])

VAULT_REF_PATTERN = re.compile(r"\{\{(\w+)\.(username|password|api_key|token|[\w]+)\}\}")


# --- Pydantic models ---

class RemoteResponse(BaseModel):
    name: str


class RemoteProjectResponse(BaseModel):
    id: int
    name: str
    base_url: str


class PromoteRequest(BaseModel):
    test_case_ids: List[int]
    project_id: int
    remote_name: str
    target_project_id: Optional[int] = None  # If set, import into this existing project on target


class FixturePayload(BaseModel):
    name: str
    description: Optional[str] = None
    setup_steps: str
    scope: str = "cached"
    cache_ttl_seconds: int = 3600


class TestCasePayload(BaseModel):
    name: str
    description: Optional[str] = None
    natural_query: str
    steps: str
    expected_result: Optional[str] = None
    tags: Optional[str] = None
    fixture_names: List[str] = []
    priority: str = "medium"
    status: str = "draft"


class ImportPayload(BaseModel):
    project_name: str
    project_base_url: str
    project_description: Optional[str] = None
    target_project_id: Optional[int] = None  # If set, import into this existing project
    test_cases: List[TestCasePayload]
    fixtures: List[FixturePayload]


class ImportResult(BaseModel):
    test_cases_created: int = 0
    test_cases_skipped: int = 0
    fixtures_created: int = 0
    fixtures_reused: int = 0
    warnings: List[str] = []


# --- Helper ---

def _detect_vault_refs(steps_json: str) -> List[str]:
    """Detect vault-style references in steps JSON."""
    matches = VAULT_REF_PATTERN.findall(steps_json)
    return list({f"{{{{{m[0]}.{m[1]}}}}}" for m in matches})


def _find_remote(name: str) -> Optional[dict]:
    """Find a configured remote by name."""
    for remote in CHECKMATE_REMOTES:
        if remote["name"] == name:
            return remote
    return None


# --- Endpoints ---

@router.get("/config/remotes", response_model=List[RemoteResponse])
def list_remotes():
    """Return configured remote environment names (URLs not exposed)."""
    return [RemoteResponse(name=r["name"]) for r in CHECKMATE_REMOTES]


@router.get("/config/remotes/{remote_name}/projects", response_model=List[RemoteProjectResponse])
async def list_remote_projects(remote_name: str):
    """Fetch projects from a remote Checkmate instance."""
    remote = _find_remote(remote_name)
    if not remote:
        raise HTTPException(status_code=400, detail=f"Unknown remote: {remote_name}")

    target_url = f"{remote['url']}/api/projects"
    headers = {}
    if CHECKMATE_API_KEY:
        headers["X-API-Key"] = CHECKMATE_API_KEY

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(target_url, headers=headers)
            resp.raise_for_status()
            projects = resp.json()
            return [
                RemoteProjectResponse(id=p["id"], name=p["name"], base_url=p["base_url"])
                for p in projects
            ]
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to remote: {remote_name}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Timeout connecting to remote: {remote_name}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Remote returned error: {e.response.status_code}")


@router.post("/test-cases/promote", response_model=ImportResult)
async def promote_test_cases(
    request: PromoteRequest,
    session: Session = Depends(get_session_dep),
):
    """Promote test cases to a remote Checkmate environment."""
    # Validate remote
    remote = _find_remote(request.remote_name)
    if not remote:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown remote: {request.remote_name}. "
                   f"Configured remotes: {[r['name'] for r in CHECKMATE_REMOTES]}",
        )

    # Fetch project
    project = crud.get_project(session, request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Fetch test cases
    test_cases = []
    for tc_id in request.test_case_ids:
        tc = crud.get_test_case(session, tc_id)
        if tc:
            test_cases.append(tc)
    if not test_cases:
        raise HTTPException(status_code=400, detail="No valid test cases found")

    # Collect referenced fixtures
    all_fixture_ids = set()
    for tc in test_cases:
        fids = tc.get_fixture_ids()
        all_fixture_ids.update(fids)
    fixtures = crud.get_fixtures_by_ids(session, list(all_fixture_ids))
    fixture_id_to_name = {f.id: f.name for f in fixtures}

    # Build payloads
    warnings = []
    tc_payloads = []
    for tc in test_cases:
        # Map fixture IDs to names
        fids = tc.get_fixture_ids()
        fixture_names = [fixture_id_to_name[fid] for fid in fids if fid in fixture_id_to_name]

        # Detect vault references
        vault_refs = _detect_vault_refs(tc.steps or "")
        if vault_refs:
            warnings.append(
                f"Test case \"{tc.name}\" references vault entries: {', '.join(vault_refs)}. "
                "Ensure matching vault entries exist on the target environment."
            )

        tc_payloads.append(TestCasePayload(
            name=tc.name,
            description=tc.description,
            natural_query=tc.natural_query,
            steps=tc.steps,
            expected_result=tc.expected_result,
            tags=tc.tags,
            fixture_names=fixture_names,
            priority=tc.priority.value if hasattr(tc.priority, 'value') else tc.priority,
            status=tc.status.value if hasattr(tc.status, 'value') else tc.status,
        ))

    fixture_payloads = [
        FixturePayload(
            name=f.name,
            description=f.description,
            setup_steps=f.setup_steps,
            scope=f.scope,
            cache_ttl_seconds=f.cache_ttl_seconds,
        )
        for f in fixtures
    ]

    payload = ImportPayload(
        project_name=project.name,
        project_base_url=project.base_url,
        project_description=project.description,
        target_project_id=request.target_project_id,
        test_cases=tc_payloads,
        fixtures=fixture_payloads,
    )

    # Send to remote
    target_url = f"{remote['url']}/api/test-cases/import"
    headers = {"Content-Type": "application/json"}
    if CHECKMATE_API_KEY:
        headers["X-API-Key"] = CHECKMATE_API_KEY

    logger.info(f"Promoting {len(tc_payloads)} test cases to {request.remote_name} ({remote['url']})")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                target_url,
                content=payload.model_dump_json(),
                headers=headers,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=502, detail="Authentication failed on target environment")
            resp.raise_for_status()
            result = ImportResult(**resp.json())
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to remote: {request.remote_name}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Timeout connecting to remote: {request.remote_name}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Remote returned error: {e.response.status_code}")

    # Merge local warnings with any remote warnings
    result.warnings = warnings + result.warnings
    return result


@router.post("/test-cases/import", response_model=ImportResult)
def import_test_cases(
    payload: ImportPayload,
    session: Session = Depends(get_session_dep),
    x_api_key: Optional[str] = Header(None),
):
    """Receive test cases from another Checkmate instance."""
    # Auth check
    if CHECKMATE_API_KEY and x_api_key != CHECKMATE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    result = ImportResult()

    # Resolve target project
    if payload.target_project_id:
        # Import into a specific existing project
        project = crud.get_project(session, payload.target_project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Target project ID {payload.target_project_id} not found")
    else:
        # Find by name or create new
        project = crud.get_project_by_name(session, payload.project_name)
        if not project:
            project = crud.create_project(session, ProjectCreate(
                name=payload.project_name,
                base_url=payload.project_base_url,
                description=payload.project_description,
            ))
            result.warnings.append(f"Created new project: {payload.project_name}")

    # Process fixtures — dedup by name
    fixture_name_to_id = {}
    for fp in payload.fixtures:
        existing = crud.get_fixture_by_name_and_project(session, project.id, fp.name)
        if existing:
            fixture_name_to_id[fp.name] = existing.id
            result.fixtures_reused += 1
        else:
            new_fixture = crud.create_fixture(session, FixtureCreate(
                project_id=project.id,
                name=fp.name,
                description=fp.description,
                setup_steps=fp.setup_steps,
                scope=fp.scope,
                cache_ttl_seconds=fp.cache_ttl_seconds,
            ))
            fixture_name_to_id[fp.name] = new_fixture.id
            result.fixtures_created += 1

    # Process test cases — skip if name already exists in project
    existing_tc_names = {
        tc.name
        for tc in crud.get_test_cases_by_project(session, project.id, limit=10000)
    }

    for tcp in payload.test_cases:
        if tcp.name in existing_tc_names:
            result.test_cases_skipped += 1
            continue

        # Remap fixture names to target IDs
        target_fixture_ids = [
            fixture_name_to_id[fn]
            for fn in tcp.fixture_names
            if fn in fixture_name_to_id
        ]

        crud.create_test_case(session, TestCaseCreate(
            project_id=project.id,
            name=tcp.name,
            description=tcp.description,
            natural_query=tcp.natural_query,
            steps=tcp.steps,
            expected_result=tcp.expected_result,
            tags=tcp.tags,
            fixture_ids=json.dumps(target_fixture_ids) if target_fixture_ids else None,
            priority=tcp.priority,
            status=tcp.status,
        ))
        result.test_cases_created += 1

    logger.info(
        f"Import complete: {result.test_cases_created} created, "
        f"{result.test_cases_skipped} skipped, "
        f"{result.fixtures_created} fixtures created, "
        f"{result.fixtures_reused} fixtures reused"
    )

    return result
