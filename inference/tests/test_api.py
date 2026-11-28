import math

import pytest

from src.main import get_top_k
from tests.conftest import DIM, GENRES, MOODS, wav_bytes

# keys that songs/src/tagger.py reads from /analyze
TAGGER_KEYS = {"p_music", "genre", "mood"}


def analyze(client, content_type="audio/wav", **params):
    return client.post("/analyze", files={"file": ("a.wav", wav_bytes(), content_type)}, params=params)


def test_get_top_k():
    assert get_top_k({"a": 0.1, "b": 0.9, "c": 0.5}, 2) == {"b": 0.9, "c": 0.5}
    assert list(get_top_k({"a": 0.1, "b": 0.9, "c": 0.5}, 3)) == ["b", "c", "a"]


def test_get_top_k_larger_than_dict():
    assert get_top_k({"a": 0.1}, 5) == {"a": 0.1}


def test_get_top_k_accepts_string():
    assert get_top_k({"a": 0.1, "b": 0.9}, "1") == {"b": 0.9}


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"loaded": True, "device": "cpu"}


def test_analyze(client):
    response = analyze(client)
    assert response.status_code == 200
    body = response.json()
    assert TAGGER_KEYS <= set(body)
    assert 0 <= body["p_music"] <= 1
    assert 0 <= body["energy"] <= 1
    assert body["windows"] == 6
    assert len(body["genre"]) == 3
    assert set(body["genre"]) <= set(GENRES)
    assert set(body["mood"]) <= set(MOODS)
    assert all(0 <= p <= 1 for p in [*body["genre"].values(), *body["mood"].values()])
    assert list(body["genre"].values()) == sorted(body["genre"].values(), reverse=True)
    assert len(body["embedding"]) == DIM
    assert math.isclose(math.fsum(x * x for x in body["embedding"]), 1.0, rel_tol=1e-3)


@pytest.mark.parametrize("top_k", [1, 2, 10])
def test_analyze_top_k(client, top_k):
    body = analyze(client, top_k=top_k).json()
    assert len(body["genre"]) == min(top_k, len(GENRES))
    assert len(body["mood"]) == min(top_k, len(MOODS))


@pytest.mark.xfail(strict=True, reason="bug: top_k has no type, so a non-number gives 500, not 422")
def test_analyze_bad_top_k_is_422(client):
    assert analyze(client, top_k="abc").status_code == 422


@pytest.mark.parametrize("content_type", ["text/plain", "image/png", "application/octet-stream"])
def test_analyze_wrong_type_is_415(client, content_type):
    assert analyze(client, content_type=content_type).status_code == 415


@pytest.mark.parametrize("content_type", ["audio/mpeg", "audio/mp4", "audio/webm", "audio/flac"])
def test_analyze_accepts_types_that_songs_sends(client, content_type):
    """songs/src/download.py MEDIA_TYPES sends these."""
    assert analyze(client, content_type=content_type).status_code == 200


def test_analyze_without_file_is_422(client):
    assert client.post("/analyze").status_code == 422
