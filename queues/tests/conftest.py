"""Test setup: a throwaway postgres database, a client, and a login helper.

The tests never use DATABASE_URL from the environment, so they cannot touch a real database.
Set TEST_DATABASE_URL to point them at another server.
"""

import os

from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
DB_NAME = "queues_test"

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


# --- fakes of the songs and auth services ---

SONGS = "http://songs:8000"
AUTH = "http://auth:8000"

HOST = 1
GUEST = 2
OTHER = 3


def song_url(song_id: int) -> str:
    return f"https://youtube.example/watch?v={song_id}"


def fake_song(song_id: int) -> dict:
    """Same keys as song_payload in the songs service."""
    return {
        "id": song_id,
        "title": f"song {song_id}",
        "artist": "artist",
        "uploader": "uploader",
        "duration": 180,
        "source_id": str(song_id),
        "source_url": song_url(song_id),
        "found_by": song_url(song_id),
        "genre": None,
        "mood": None,
        "quality": None,
        "filename": f"{song_id}.mp3",
    }


@pytest.fixture
def services():
    """Mocks songs and auth. A request for song_url(n) gives song n."""
    import json

    import httpx
    import respx

    def from_url(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["query"]
        return httpx.Response(200, json={"song": fake_song(int(query.rsplit("=", 1)[1]))})

    def by_ids(request: httpx.Request) -> httpx.Response:
        ids = [int(i) for i in request.url.params.get_list("ids")]
        return httpx.Response(200, json={"songs": [fake_song(i) for i in ids]})

    def names(request: httpx.Request) -> httpx.Response:
        ids = request.url.params.get_list("ids")
        return httpx.Response(200, json={i: f"user{i}" for i in ids})

    with respx.mock(assert_all_called=False) as router:
        router.post(f"{SONGS}/internal/songs/from-url", name="from_url").mock(side_effect=from_url)
        router.get(f"{SONGS}/internal/songs", name="by_ids").mock(side_effect=by_ids)
        router.get(f"{AUTH}/internal/users/names", name="names").mock(side_effect=names)
        yield router


@pytest.fixture
def published(monkeypatch):
    """List of (room_id, event) that the routes publish."""
    from src.events import events

    sent: list[tuple[int, dict]] = []
    original = events.publish

    def record(room_id: int, event: dict) -> None:
        sent.append((room_id, event))
        original(room_id, event)

    monkeypatch.setattr(events, "publish", record)
    return sent
