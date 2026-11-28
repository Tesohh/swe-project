"""Calls to the songs and auth services, and the internal route that auth calls."""

import httpx
import pytest
from sqlmodel import select

from src.models import QueueItem, Room, Vote
from tests.conftest import GUEST, HOST, OTHER, song_url
from tests.helpers import add_requested, as_user, create_room, request_song


@pytest.fixture
def room(client, services) -> int:
    return create_room(client)


def test_request_sends_query_to_songs(client, room, services):
    request_song(client, room, 4)
    sent = services["from_url"].calls.last.request
    assert sent.read() == f'{{"query":"{song_url(4)}"}}'.encode()


def test_songs_4xx_keeps_status(client, room, services):
    services["from_url"].respond(422, json={"detail": "Only a song url is accepted for now"})
    response = request_song(client, room, 1)
    assert response.status_code == 422
    assert response.json()["detail"] == "Only a song url is accepted for now"


def test_songs_5xx_is_502(client, room, services):
    services["from_url"].respond(500)
    assert request_song(client, room, 1).status_code == 502


def test_songs_down_is_502(client, room, services):
    services["from_url"].mock(side_effect=httpx.ConnectError("down"))
    assert request_song(client, room, 1).status_code == 502


def test_missing_song_in_queue_read_is_502(client, room, services):
    add_requested(client, room, 1)
    services["by_ids"].respond(200, json={"songs": []})
    as_user(client, GUEST)
    assert client.get(f"/room/{room}/queue").status_code == 502


def test_auth_down_keeps_queue_without_names(client, room, services):
    add_requested(client, room, 1)
    services["names"].mock(side_effect=httpx.ConnectError("down"))
    as_user(client, GUEST)
    response = client.get(f"/room/{room}/queue")
    assert response.status_code == 200
    assert response.json()["pending"][0]["added_by_name"] is None


def test_song_lookup_sends_unique_ids(client, room, services):
    add_requested(client, room, 2)
    add_requested(client, room, 1)
    as_user(client, GUEST)
    client.get(f"/room/{room}/queue")
    params = services["by_ids"].calls.last.request.url.params.get_list("ids")
    assert params == ["1", "2"]


# --- /internal/users/{id} ---


def test_delete_user_data(client, services, session, published):
    own_room = create_room(client, "own", host=OTHER)
    add_requested(client, own_room, 1, user=GUEST)

    other_room = create_room(client, "other", host=HOST)
    entry = add_requested(client, other_room, 2, user=OTHER)
    add_requested(client, other_room, 3, user=GUEST)  # stays

    response = client.delete(f"/internal/users/{OTHER}")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "rooms_deleted": 1}

    session.expire_all()
    assert session.get(Room, own_room) is None
    assert session.exec(select(QueueItem).where(QueueItem.room_id == own_room)).all() == []
    assert session.exec(select(Vote).where(Vote.user_id == OTHER)).all() == []
    assert session.get(QueueItem, entry).added_by is None
    assert len(session.exec(select(Vote).where(Vote.user_id == GUEST)).all()) == 1
    assert (own_room, {"topic": "room", "type": "deleted"}) in published


def test_delete_user_without_data(client, services):
    response = client.delete("/internal/users/999")
    assert response.status_code == 200
    assert response.json()["rooms_deleted"] == 0
