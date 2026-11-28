import pytest
from fastapi import HTTPException

import src.download
from src.download import download_url, song_file


@pytest.fixture
def songs_dir():
    src.download.SONGS_DIR.mkdir(parents=True)
    return src.download.SONGS_DIR


def test_song_file_none_id():
    assert song_file(None) is None


def test_song_file_missing(songs_dir):
    assert song_file(1) is None


def test_song_file_found(songs_dir):
    (songs_dir / "1.m4a").write_bytes(b"x")
    assert song_file(1) == songs_dir / "1.m4a"


@pytest.mark.parametrize("name", ["1.mp3.part", "1.webm.ytdl", "1.partial", "1.frag"])
def test_song_file_ignores_partials(songs_dir, name):
    (songs_dir / name).write_bytes(b"x")
    assert song_file(1) is None


def test_song_file_does_not_match_other_ids(songs_dir):
    (songs_dir / "11.mp3").write_bytes(b"x")
    assert song_file(1) is None


@pytest.mark.parametrize("url", ["http://a.example/x", "https://a.example/x"])
def test_download_url_accepts_urls(url):
    assert download_url(url) == url


@pytest.mark.parametrize("query", ["despacito", "ftp://a.example/x", ""])
def test_download_url_refuses_other_text(query):
    with pytest.raises(HTTPException) as err:
        download_url(query)
    assert err.value.status_code == 422
