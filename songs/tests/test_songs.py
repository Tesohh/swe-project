import httpx
import pytest
from sqlmodel import select

import src.download
from src.models import Song
from tests.conftest import TAG_RESULT, video_url

ABC = video_url("abc")

# keys that the queues service and the frontend read from a song payload
PAYLOAD_KEYS = {
    "id",
    "title",
    "artist",
    "uploader",
    "duration",
    "source_id",
    "source_url",
    "found_by",
    "genre",
    "mood",
    "quality",
    "filename",
}


def download(client, url=ABC):
    return client.post("/song/download", params={"url": url})


def songs_on_disk() -> list[str]:
    return sorted(path.name for path in src.download.SONGS_DIR.glob("*"))


# --- download ---


def test_download_stores_row_and_file(client, session, ydl):
    response = download(client)
    assert response.status_code == 200
    song = response.json()["song"]
    assert set(song) == PAYLOAD_KEYS
    assert song["title"] == "Song ABC"
    assert song["artist"] == "Chan"  # no artist field, so the uploader
    assert song["source_url"] == ABC
    assert song["found_by"] == ABC
    assert song["source_id"] == "abc"
    assert song["duration"] == 200
    assert song["filename"] == f"{song['id']}.mp3"
    assert songs_on_disk() == [f"{song['id']}.mp3"]
    assert session.get(Song, song["id"]) is not None


def test_download_uses_artist_when_present(client, ydl):
    ydl.infos[ABC]["artist"] = "Real Artist"
    assert download(client).json()["song"]["artist"] == "Real Artist"


def test_download_same_url_reuses_row(client, session, ydl):
    first = download(client).json()["song"]["id"]
    second = download(client).json()["song"]["id"]
    assert first == second
    assert len(session.exec(select(Song)).all()) == 1
    assert ydl.extract_calls == [ABC]
    assert ydl.download_calls == [ABC]


def test_download_reuse_restores_missing_file(client, ydl):
    song_id = download(client).json()["song"]["id"]
    (src.download.SONGS_DIR / f"{song_id}.mp3").unlink()
    assert download(client).status_code == 200
    assert songs_on_disk() == [f"{song_id}.mp3"]
    assert ydl.download_calls == [ABC, ABC]


def test_download_search_text_is_422(client, ydl):
    assert download(client, "despacito").status_code == 422
    assert ydl.extract_calls == []


def test_download_unreadable_url_is_400(client, session):
    assert download(client, video_url("nope")).status_code == 400
    assert session.exec(select(Song)).all() == []


def test_download_without_title_is_400(client, session, ydl):
    ydl.infos[ABC] = {"id": "abc"}
    assert download(client).status_code == 400
    assert session.exec(select(Song)).all() == []


def test_failed_download_removes_row_and_partials(client, session, ydl):
    ydl.fail_download.add(ABC)
    assert download(client).status_code == 502
    assert session.exec(select(Song)).all() == []
    assert songs_on_disk() == []


def test_download_without_file_is_502(client, session, ydl):
    ydl.write_nothing.add(ABC)
    assert download(client).status_code == 502
    assert session.exec(select(Song)).all() == []


# --- tagger ---


def test_tagger_result_is_stored(client, tagger, session):
    song = download(client).json()["song"]
    assert song["genre"] == "rock"
    assert song["mood"] == "happy"
    assert song["quality"] == "good"
    request = tagger["analyze"].calls.last.request
    assert request.url.params["top_k"] == "1"
    assert b'filename="' in request.read()


def test_low_p_music_is_not_music(client, tagger):
    tagger["analyze"].respond(200, json={**TAG_RESULT, "p_music": 0.1})
    assert download(client).json()["song"]["quality"] == "not_music"


@pytest.mark.parametrize(
    "failure",
    [
        {"side_effect": httpx.ConnectError("down")},
        {"side_effect": httpx.ReadTimeout("slow")},
        {"return_value": httpx.Response(500)},
        {"return_value": httpx.Response(200, text="not json")},
    ],
)
def test_tagger_failure_keeps_song_untagged(client, tagger, failure):
    tagger["analyze"].mock(**failure)
    response = download(client)
    assert response.status_code == 200
    song = response.json()["song"]
    assert (song["genre"], song["mood"], song["quality"]) == (None, None, None)


def test_tagger_bad_json_shape_keeps_song_untagged(client, tagger):
    tagger["analyze"].respond(200, json={"p_music": 0.9})
    assert download(client).status_code == 200


def test_reused_song_is_not_tagged_again(client, tagger):
    download(client)
    download(client)
    assert tagger["analyze"].call_count == 1


# --- info / stream ---


def test_info(client):
    song_id = download(client).json()["song"]["id"]
    response = client.get(f"/song/info/{song_id}")
    assert response.status_code == 200
    assert response.json()["song"]["id"] == song_id


def test_info_unknown_is_404(client):
    assert client.get("/song/info/999").status_code == 404


def test_stream(client):
    song_id = download(client).json()["song"]["id"]
    response = client.get(f"/song/stream/{song_id}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == (src.download.SONGS_DIR / f"{song_id}.mp3").read_bytes()


def test_stream_range(client):
    song_id = download(client).json()["song"]["id"]
    response = client.get(f"/song/stream/{song_id}", headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert len(response.content) == 10


def test_stream_unknown_is_404(client):
    assert client.get("/song/stream/999").status_code == 404


def test_stream_redownloads_missing_file(client, ydl):
    song_id = download(client).json()["song"]["id"]
    (src.download.SONGS_DIR / f"{song_id}.mp3").unlink()
    assert client.get(f"/song/stream/{song_id}").status_code == 200
    assert ydl.download_calls == [ABC, ABC]


def test_stream_redownload_failure_is_502(client, ydl):
    song_id = download(client).json()["song"]["id"]
    (src.download.SONGS_DIR / f"{song_id}.mp3").unlink()
    ydl.fail_download.add(ABC)
    assert client.get(f"/song/stream/{song_id}").status_code == 502


def test_stream_without_source_url_is_500(client, session):
    song = Song(title="t", artist=None, found_by="x", source_url=None)
    session.add(song)
    session.commit()
    assert client.get(f"/song/stream/{song.id}").status_code == 500


# --- search ---


def test_search(client, ydl):
    ydl.search_result = {
        "entries": [{"title": "A", "webpage_url": ABC, "thumbnail": "t.jpg", "duration": 10, "extra": 1}],
    }
    response = client.get("/song/search", params={"query": "abc"})
    assert response.status_code == 200
    assert response.json()["results"] == [{"title": "A", "url": ABC, "thumbnail": "t.jpg", "duration": 10}]
    assert ydl.extract_calls == ["ytsearch5:abc"]


def test_search_without_results(client, ydl):
    assert client.get("/song/search", params={"query": "abc"}).json()["results"] == []


# --- internal ---


def test_internal_from_url(client):
    response = client.post("/internal/songs/from-url", json={"query": ABC})
    assert response.status_code == 200
    assert set(response.json()["song"]) == PAYLOAD_KEYS


def test_internal_from_url_empty_query_is_422(client):
    assert client.post("/internal/songs/from-url", json={"query": ""}).status_code == 422


def test_internal_from_url_search_text_is_422(client):
    assert client.post("/internal/songs/from-url", json={"query": "despacito"}).status_code == 422


def test_internal_songs_by_ids(client):
    song_id = download(client).json()["song"]["id"]
    response = client.get("/internal/songs", params={"ids": [song_id, 999]})
    assert response.status_code == 200
    songs = response.json()["songs"]
    assert [song["id"] for song in songs] == [song_id]
    assert set(songs[0]) == PAYLOAD_KEYS


def test_internal_songs_without_ids(client):
    assert client.get("/internal/songs").json() == {"songs": []}
