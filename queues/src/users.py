"""Client of the auth service. The queues service keeps only user ids."""

import logging

from common.http import base_url, call
from fastapi import HTTPException

log = logging.getLogger(__name__)


def names_by_id(ids: list[int]) -> dict[int, str]:
    """User names by user id. If auth is down the names are left out, the queue still works."""
    wanted = sorted(set(ids))
    if not wanted:
        return {}
    try:
        response = call("auth", "GET", f"{base_url('AUTH_BASE', 'http://auth:8000')}/internal/users/names", params={"ids": wanted})
    except HTTPException as err:
        log.warning("no user names: %s", err.detail)
        return {}
    return {int(user_id): name for user_id, name in response.json().items()}
