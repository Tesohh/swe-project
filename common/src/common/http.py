"""HTTP client for calls from one service to another.

Services call each other directly by their compose hostname, never through the gateway.
"""

import logging
import os
from typing import Any

import httpx
from fastapi import HTTPException, status

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0


def base_url(env_name: str, default: str) -> str:
    """Base url of another service, from the environment."""
    return os.environ.get(env_name, default).rstrip("/")


async def call(
    service: str,
    method: str,
    url: str,
    *,
    timeout: float = TIMEOUT_SECONDS,
    **kwargs: Any,
) -> httpx.Response:
    """Sends a request to another service.

    A service that is down or answers with an error becomes 502 for our caller.
    A 4xx answer keeps its status and detail, so the user sees the real reason.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as err:
        log.warning("%s service unreachable: %s", service, err)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The {service} service is not available"
        ) from err

    if response.status_code >= 500:
        log.warning(
            "%s service failed: %s %s",
            service,
            response.status_code,
            response.text[:200],
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The {service} service failed"
        )
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HTTPException(response.status_code, detail)
    return response
