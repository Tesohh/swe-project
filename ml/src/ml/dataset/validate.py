"""Whole-manifest checks that look across rows, not into single rows."""

from collections import Counter
from itertools import groupby

from pydantic import BaseModel

from ml.dataset.manifest import Manifest, ManifestRow
from ml.dataset.vocabs import AudioType, load_genres, load_moods


class CrossCheckError(BaseModel):
    """One whole-manifest problem, reported with a row url for context."""

    kind: str
    detail: str
    row_id: str = ""


class ManifestReport(BaseModel):
    """Everything dataset-check knows about one manifest."""

    manifest: Manifest
    cross_errors: list[CrossCheckError]
    genre_counts: Counter[str]
    mood_counts: Counter[str]
    source_counts: Counter[str]
    audio_type_counts: Counter[str]

    @property
    def is_valid(self) -> bool:
        return self.manifest.is_valid and not self.cross_errors


def check_manifest(manifest: Manifest) -> ManifestReport:
    cross_errors: list[CrossCheckError] = []
    cross_errors += _find_url_duplicates(manifest.rows)
    cross_errors += _find_unknown_tags(manifest.rows)
    cross_errors += _find_title_duplicates(manifest.rows)
    return ManifestReport(
        manifest=manifest,
        cross_errors=cross_errors,
        genre_counts=Counter(tag for row in manifest.rows for tag in row.genre),
        mood_counts=Counter(tag for row in manifest.rows for tag in row.mood),
        source_counts=Counter(row.source.value for row in manifest.rows),
        audio_type_counts=Counter(row.audio_type.value for row in manifest.rows),
    )


def _find_url_duplicates(rows: list[ManifestRow]) -> list[CrossCheckError]:
    direct = [row for row in rows if row.url is not None]
    errors = []
    for url, group in groupby(
        sorted(direct, key=lambda row: str(row.url)), key=lambda row: str(row.url)
    ):
        duplicates = list(group)[1:]
        errors += [
            CrossCheckError(kind="duplicate_url", detail=url, row_id=dup.id) for dup in duplicates
        ]
    return errors


def _find_title_duplicates(rows: list[ManifestRow]) -> list[CrossCheckError]:
    # Same title and artist from different urls is most often the same upload
    errors = []

    def title_artist(row: ManifestRow) -> tuple[str, str]:
        return (row.title.lower(), row.artist.lower())

    for _, group in groupby(sorted(rows, key=title_artist), key=title_artist):
        duplicates = list(group)[1:]
        errors += [
            CrossCheckError(kind="duplicate_title", detail=dup.title, row_id=dup.id)
            for dup in duplicates
        ]
    return errors


def _find_unknown_tags(rows: list[ManifestRow]) -> list[CrossCheckError]:
    genres = load_genres()
    moods = load_moods()
    errors = []
    for row in rows:
        for tag in row.genre:
            if tag not in genres:
                errors.append(CrossCheckError(kind="unknown_genre", detail=tag, row_id=row.id))
        for tag in row.mood:
            if tag not in moods:
                errors.append(CrossCheckError(kind="unknown_mood", detail=tag, row_id=row.id))
        if row.audio_type != AudioType.MUSIC and (row.genre or row.mood):
            tagged = ", ".join(row.genre + row.mood)
            errors.append(CrossCheckError(kind="non_music_tagged", detail=tagged, row_id=row.id))
    return errors
