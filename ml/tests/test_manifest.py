"""Tests for the manifest format and the cross checks."""

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from ml.dataset.manifest import ManifestRow, load_manifest
from ml.dataset.validate import check_manifest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _broken_csv() -> Path:
    return FIXTURES / "manifest_broken.csv"


@pytest.fixture
def sample_manifest():
    return load_manifest(FIXTURES / "manifest_sample.csv")


def test_sample_rows_parse(sample_manifest):
    manifest = sample_manifest
    assert len(manifest.errors) == 0
    assert len(manifest.rows) == 3


def test_ids_generated_when_blank(sample_manifest):
    manifest = sample_manifest
    generated = [row.id for row in manifest.rows if row.genre == ["folk", "rock", "country"]]
    assert generated and generated[0]


def test_speech_row_untagged_is_valid(sample_manifest):
    manifest = sample_manifest
    speech = next(row for row in manifest.rows if row.audio_type.value == "speech")
    assert speech.genre == []
    assert speech.mood == []
    assert speech.id  # generated when blank


def test_each_broken_row_is_caught():
    report = check_manifest(load_manifest(_broken_csv()))
    details = [error.error for error in report.manifest.errors]

    # row 2: duplicate url
    assert len([e for e in report.cross_errors if e.kind == "duplicate_url"]) == 1
    # rows 4 and 5: duplicate title with same artist
    assert len([e for e in report.cross_errors if e.kind == "duplicate_title"]) >= 1
    # row 6: unknown genre, row 7: unknown mood
    assert len([e for e in report.cross_errors if e.kind == "unknown_genre"]) == 1
    assert len([e for e in report.cross_errors if e.kind == "unknown_mood"]) == 1
    # row 8: noise with genre tags; blank trailing row ignored
    assert len([e for e in report.cross_errors if e.kind == "non_music_tagged"]) == 1
    assert not any("url" in detail for detail in details)


def test_query_only_row_is_valid():
    row = ManifestRow(
        title="Smells Like Teen Spirit",
        artist="Nirvana",
        source="youtube",
        genre=["rock"],
        label_origin="agent",
    )
    assert row.url is None
    assert row.query == ""
    # neither url, query nor title+artist to search must fail
    with pytest.raises(
        ValidationError, match="row needs a url, a query, or artist plus title to search"
    ):
        ManifestRow(source="youtube", label_origin="agent")


def test_counts_per_row(sample_manifest):
    report = check_manifest(sample_manifest)
    assert report.genre_counts == Counter({"folk": 1, "rock": 1, "country": 1, "electronic": 1})
    assert report.audio_type_counts == Counter({"music": 2, "speech": 1})
    assert report.is_valid
