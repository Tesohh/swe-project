"""Test setup: a throwaway postgres database, a client, and a login helper.

The tests never use DATABASE_URL from the environment, so they cannot touch a real database.
Set TEST_DATABASE_URL to point them at another server.
"""

import os

from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
DB_NAME = "songs_test"

os.environ["DATABASE_URL"] = make_url(TEST_DATABASE_URL).set(database=DB_NAME).render_as_string(hide_password=False)
os.environ["JWT_SECRET_KEY"] = "test-secret"


def _create_database() -> None:
    import psycopg2

    server = make_url(TEST_DATABASE_URL)
    conn = psycopg2.connect(
        host=server.host,
        port=server.port or 5432,
        user=server.username,
        password=server.password,
        dbname=server.database or "postgres",
    )
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        if cursor.fetchone() is None:
            cursor.execute(f'CREATE DATABASE "{DB_NAME}"')
    conn.close()


_create_database()

import pytest
from common.auth import TOKEN_COOKIE, create_access_token
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel

import src.db
import src.main


@pytest.fixture(autouse=True)
def tables():
    """Fresh tables for every test."""
    SQLModel.metadata.drop_all(src.db.engine)
    SQLModel.metadata.create_all(src.db.engine)
    yield


@pytest.fixture
def session():
    with Session(src.db.engine) as session:
        yield session


def token_for(user_id: int) -> str:
    return create_access_token({"sub": str(user_id)})


@pytest.fixture
def client() -> TestClient:
    # https, because the auth cookie is secure. No "with", so the lifespan does not run.
    # A server error becomes a 500 response, as a real client sees it
    return TestClient(src.main.app, base_url="https://testserver", raise_server_exceptions=False)


@pytest.fixture
def login(client):
    """login(user_id) sets the token cookie of user_id on client."""

    def _login(user_id: int) -> TestClient:
        client.cookies.set(TOKEN_COOKIE, token_for(user_id))
        return client

    return _login


# --- fakes of yt-dlp and the tagger ---

from typing import ClassVar

TAGGER = "http://inference:8000/analyze"


def video_url(video_id: str) -> str:
    return f"https://youtube.example/watch?v={video_id}"


class FakeYDL:
    """Stand-in for yt_dlp.YoutubeDL. infos maps url -> info dict; fail_download holds urls whose download fails."""

    infos: ClassVar[dict[str, dict]] = {}
    fail_download: ClassVar[set[str]] = set()
    write_nothing: ClassVar[set[str]] = set()
    extract_calls: ClassVar[list[str]] = []
    download_calls: ClassVar[list[str]] = []
    search_result: ClassVar[dict | None] = None

    def __init__(self, opts: dict):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url: str, download: bool = False):
        import yt_dlp

        FakeYDL.extract_calls.append(url)
        if url.startswith("ytsearch"):
            return FakeYDL.search_result
        if url not in FakeYDL.infos:
            raise yt_dlp.utils.DownloadError(f"unsupported url {url}")
        return FakeYDL.infos[url]

    def download(self, urls: list[str]):
        from pathlib import Path

        import yt_dlp

        url = urls[0]
        FakeYDL.download_calls.append(url)
        template = self.opts["outtmpl"]
        if url in FakeYDL.fail_download:
            Path(template.replace("%(ext)s", "mp3.part")).write_bytes(b"partial")
            raise yt_dlp.utils.DownloadError("network error")
        if url in FakeYDL.write_nothing:
            return
        Path(template.replace("%(ext)s", "mp3")).write_bytes(b"ID3 fake mp3 " * 100)


@pytest.fixture(autouse=True)
def ydl(monkeypatch, tmp_path):
    """Fake yt-dlp, and songs saved under tmp_path. Each test starts with one known video, "abc"."""
    import yt_dlp

    import src.download

    monkeypatch.setattr(src.download, "SONGS_DIR", tmp_path / "songs")
    FakeYDL.infos = {video_url("abc"): {"id": "abc", "title": "Song ABC", "uploader": "Chan", "duration": 200}}
    FakeYDL.fail_download = set()
    FakeYDL.write_nothing = set()
    FakeYDL.extract_calls = []
    FakeYDL.download_calls = []
    FakeYDL.search_result = None
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    return FakeYDL


TAG_RESULT = {
    "p_music": 0.9,
    "genre": {"rock": 0.8},
    "mood": {"happy": 0.7},
    "energy": 0.5,
    "windows": 6,
    "embedding": [0.0] * 4,
}


@pytest.fixture(autouse=True)
def tagger():
    """Fake tagger. It answers TAG_RESULT unless a test changes the route."""
    import respx

    with respx.mock(assert_all_called=False) as router:
        router.post(TAGGER, name="analyze").respond(200, json=TAG_RESULT)
        yield router
