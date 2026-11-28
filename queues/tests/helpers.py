"""Actions and checks that many queue tests share."""

from common.auth import TOKEN_COOKIE
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import src.db
from src.models import QueueItem
from tests.conftest import GUEST, HOST, song_url, token_for


def as_user(client: TestClient, user_id: int) -> TestClient:
    client.cookies.set(TOKEN_COOKIE, token_for(user_id))
    return client


def create_room(client: TestClient, name: str = "beach", host: int = HOST, **body) -> int:
    as_user(client, host)
    response = client.post("/room/create", json={"name": name, **body})
    assert response.status_code == 201, response.text
    return response.json()["room_id"]


def request_song(client: TestClient, room_id: int, song_id: int, user: int = GUEST):
    as_user(client, user)
    return client.post(f"/room/{room_id}/queue/request", json={"query": song_url(song_id)})


def add_requested(client: TestClient, room_id: int, song_id: int, user: int = GUEST) -> int:
    response = request_song(client, room_id, song_id, user)
    assert response.status_code == 201, response.text
    return response.json()["entry"]["id"]


def host_put(client: TestClient, path: str, **kwargs):
    as_user(client, HOST)
    return client.put(path, **kwargs)


def add_queued(client: TestClient, room_id: int, song_id: int, user: int = GUEST) -> int:
    """Requests song_id (with an upvote from user) and accepts it into the order."""
    entry_id = add_requested(client, room_id, song_id, user)
    response = host_put(client, f"/room/{room_id}/queue/temp_accept/{entry_id}")
    assert response.status_code == 200, response.text
    return entry_id


def entries(room_id: int) -> list[QueueItem]:
    with Session(src.db.engine) as session:
        return list(session.exec(select(QueueItem).where(QueueItem.room_id == room_id)).all())


def by_id(room_id: int) -> dict[int, QueueItem]:
    return {entry.id: entry for entry in entries(room_id)}  # type: ignore[misc]


def order(room_id: int) -> list[int]:
    """Ids of queued/playing/paused entries, by position."""
    rows = [e for e in entries(room_id) if e.position is not None]
    return [e.id for e in sorted(rows, key=lambda e: e.position)]  # type: ignore[misc]


def check_invariants(room_id: int) -> None:
    """The rules of the queue order that every action must keep."""
    rows = entries(room_id)
    ordered = [e for e in rows if e.state in ("queued", "playing", "paused")]
    positions = sorted(e.position for e in ordered)  # type: ignore[type-var]
    assert positions == list(range(len(ordered))), f"positions not dense: {[(e.id, e.state, e.position) for e in rows]}"
    assert len([e for e in rows if e.state in ("playing", "paused")]) <= 1
    for e in rows:
        if e.state in ("requested", "played"):
            assert e.position is None, f"entry {e.id} is {e.state} with position {e.position}"
