"""Response models shared by the services, so the OpenAPI documents of all services agree."""

from typing import Any

from pydantic import BaseModel


class Status(BaseModel):
    """Plain answer of a route that has nothing to return."""

    status: str = "ok"


class ErrorDetail(BaseModel):
    """Body of every error answer of FastAPI."""

    detail: str


class SongPayload(BaseModel):
    """A song row as a client sees it, plus the file name the audio is saved under."""

    id: int | None
    title: str
    artist: str | None
    uploader: str | None
    duration: int | None
    source_id: str | None
    source_url: str | None
    found_by: str | None
    genre: str | None
    mood: str | None
    quality: str | None
    filename: str | None


ERROR_DESCRIPTIONS = {
    400: "The request cannot be processed",
    401: "Not logged in, or the credentials are wrong",
    403: "The user is not allowed to do this",
    404: "The resource does not exist",
    409: "The request conflicts with the current state",
    415: "Unsupported media type",
    422: "The request is not valid",
    502: "Another service is not available or failed",
}


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """The `responses` argument of a route, with the error body model for each status code."""
    return {code: {"model": ErrorDetail, "description": ERROR_DESCRIPTIONS[code]} for code in codes}
