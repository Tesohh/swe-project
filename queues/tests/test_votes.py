import pytest

from tests.conftest import GUEST, HOST, OTHER
from tests.helpers import add_requested, as_user, create_room


@pytest.fixture
def room(client, services) -> int:
    return create_room(client)


@pytest.fixture
def entry(client, room) -> int:
    return add_requested(client, room, 1, GUEST)  # GUEST upvotes on request


def vote(client, room, entry, user, direction=None):
    as_user(client, user)
    params = {"direction": direction} if direction else {}
    return client.put(f"/room/{room}/queue/vote/{entry}", params=params)


def test_upvote_by_default(client, room, entry, published):
    response = vote(client, room, entry, OTHER)
    assert response.status_code == 200
    body = response.json()["entry"]
    assert body["score"] == 2
    assert body["my_vote"] == 1
    assert (room, {"topic": "queue", "type": "voted", "entry_id": entry, "weight": 1}) in published


def test_downvote(client, room, entry):
    body = vote(client, room, entry, OTHER, "down").json()["entry"]
    assert body["score"] == 0
    assert body["my_vote"] == -1
    assert body["playable"] is False


def test_vote_twice_counts_once(client, room, entry):
    vote(client, room, entry, OTHER)
    body = vote(client, room, entry, OTHER).json()["entry"]
    assert body["score"] == 2


def test_change_vote_direction(client, room, entry):
    body = vote(client, room, entry, GUEST, "down").json()["entry"]
    assert body["score"] == -1
    assert body["my_vote"] == -1


def test_clear_vote(client, room, entry, published):
    as_user(client, GUEST)
    response = client.delete(f"/room/{room}/queue/vote/{entry}")
    assert response.status_code == 200
    body = response.json()["entry"]
    assert body["score"] == 0
    assert body["my_vote"] is None
    assert (room, {"topic": "queue", "type": "unvoted", "entry_id": entry}) in published


def test_clear_vote_without_vote_is_ok(client, room, entry):
    as_user(client, OTHER)
    assert client.delete(f"/room/{room}/queue/vote/{entry}").status_code == 200


def test_bad_direction_is_422(client, room, entry):
    assert vote(client, room, entry, OTHER, "sideways").status_code == 422


def test_vote_needs_login(client, room, entry):
    client.cookies.clear()
    assert client.put(f"/room/{room}/queue/vote/{entry}").status_code == 403


def test_vote_unknown_entry_is_404(client, room, entry):
    assert vote(client, room, 999, OTHER).status_code == 404


def test_vote_unknown_room_is_404(client, room, entry):
    assert vote(client, 999, entry, OTHER).status_code == 404


def test_vote_entry_of_other_room_is_404(client, room, entry):
    other_room = create_room(client, "other")
    assert vote(client, other_room, entry, OTHER).status_code == 404


def test_my_vote_is_per_user(client, room, entry):
    vote(client, room, entry, OTHER, "down")
    as_user(client, HOST)
    pending = client.get(f"/room/{room}/queue").json()["pending"][0]
    assert pending["score"] == 0
    assert pending["my_vote"] is None
