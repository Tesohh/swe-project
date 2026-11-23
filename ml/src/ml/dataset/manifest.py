"""Collect-stage manifest format.

One CSV row per song to fetch, with labels attached at collect time.
The download stage later joins its outputs back onto rows by url.
"""

import csv
import uuid
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
    model_validator,
)

from ml.dataset.vocabs import AudioType, LabelOrigin, Source

# Multi-label tags use this separator inside one CSV cell
TAG_SEPARATOR = "|"


class ManifestRow(BaseModel):
    """One song to fetch. Labels are attached here, at collect time."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("id", mode="before")
    @classmethod
    def blank_id_generates_uuid(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return str(uuid.uuid4())
        return value

    url: HttpUrl | None = None

    @field_validator("url", mode="before")
    @classmethod
    def blank_url_means_none(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    # rows without url must carry a search query, checked below
    query: str = ""

    title: str = Field(min_length=1)
    artist: str = ""
    source: Source
    genre: list[str] = []
    mood: list[str] = []
    audio_type: AudioType = AudioType.MUSIC
    label_origin: LabelOrigin
    notes: str = ""

    @field_validator("audio_type", mode="before")
    @classmethod
    def empty_audio_type_means_music(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return AudioType.MUSIC
        return value

    @field_validator("genre", "mood", mode="before")
    @classmethod
    def split_tags(cls, value: object) -> object:
        if isinstance(value, str):
            return [tag for tag in (part.strip() for part in value.split(TAG_SEPARATOR)) if tag]
        return value

    @field_validator("genre", "mood")
    @classmethod
    def no_duplicate_tags(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate tag")
        return value

    @model_validator(mode="after")
    def check_labels_present(self) -> "ManifestRow":
        # download searches by query, falling back to artist - title
        has_search = bool(self.query) or (self.url is None and self.title and self.artist)
        if self.url is None and not has_search:
            raise ValueError("row needs a url, a query, or artist plus title to search")
        return self


class ManifestError(BaseModel):
    """A row that failed validation, with its line in the CSV."""

    line: int
    url: str = ""
    title: str = ""
    error: str


class Manifest(BaseModel):
    """Parsed result of one manifest CSV."""

    path: Path
    rows: list[ManifestRow]
    errors: list[ManifestError]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def load_manifest(path: Path) -> Manifest:
    """Parse a manifest CSV, keeping per-row errors instead of failing fast."""
    rows: list[ManifestRow] = []
    errors: list[ManifestError] = []
    with path.open(newline="") as file:
        for line_number, raw in enumerate(csv.DictReader(file), start=2):
            # Drop fully empty rows
            if not any((value or "").strip() for value in raw.values()):
                continue
            try:
                rows.append(ManifestRow(**raw))
            except ValidationError as exc:
                errors.append(
                    ManifestError(
                        line=line_number,
                        url=raw.get("url") or "",
                        title=raw.get("title") or "",
                        error=_format_error(exc),
                    )
                )
    return Manifest(path=path, rows=rows, errors=errors)


def _format_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        parts.append(f"{location}: {error['msg']}" if location else error["msg"])
    return "; ".join(parts)
