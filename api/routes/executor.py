"""Relay routes for executor configuration.

Proxies GET/POST /config to the Playwright executor service so the frontend
can manage browser pre-warm settings without direct access to the executor.
"""

import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/executor", tags=["executor"])

EXECUTOR_URL = os.getenv("PLAYWRIGHT_EXECUTOR_URL", "http://localhost:8932")


class ExecutorConfigUpdate(BaseModel):
    preload: bool


class CapabilitiesResponse(BaseModel):
    recording_available: bool
    headed_browsers: list[str]


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_executor_capabilities():
    """Check executor capabilities (e.g. whether recording is possible).

    Recording requires a headed (non-headless) browser. In headless-only
    environments (e.g. Kubernetes), recording is not available.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{EXECUTOR_URL}/browsers", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            headed = [
                b["id"] for b in data.get("browsers", []) if not b.get("headless", True)
            ]
            return CapabilitiesResponse(
                recording_available=len(headed) > 0,
                headed_browsers=headed,
            )
    except httpx.RequestError as exc:
        logger.warning(f"Executor unreachable when checking capabilities: {exc}")
        return CapabilitiesResponse(recording_available=False, headed_browsers=[])


@router.get("/config")
async def get_executor_config():
    """Fetch executor configuration (preload flag + browser running status)."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{EXECUTOR_URL}/config", timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Executor unreachable: {exc}")
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)


@router.post("/config")
async def update_executor_config(update: ExecutorConfigUpdate):
    """Update executor runtime configuration (preload flag).

    Setting preload=true starts any idle configured browsers immediately.
    Setting preload=false only flips the flag; running browsers stay open.
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{EXECUTOR_URL}/config",
                json=update.model_dump(),
                timeout=30.0,  # starting browsers can take a few seconds each
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Executor unreachable: {exc}")
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
