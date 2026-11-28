"""Queue order: requests, accept, move, next, prev, toggle, ban, remove.

check_invariants runs after each action, so a broken order fails the test that broke it.
"""

import pytest

from tests.conftest import GUEST, HOST, OTHER
from tests.helpers import (
    add_queued,
    add_requested,
    as_user,
    by_id,
    check_invariants,
    create_room,
    host_put,
    order,
    request_song,
)


@pytest.fixture
def room(client, services) -> int:
    return create_room(client)


def queue_of(client, room_id: int) -> dict:
    as_user(client, GUEST)
    response = client.get(f"/room/{room_id}/queue")
    assert response.status_code == 200, response.text
    return response.json()


def playing(room_id: int):
    return [e for e in by_id(room_id).values() if e.state in ("playing", "paused")]


# --- request ---


def test_request_creates_requested_entry_with_upvote(client, room, published):
    response = request_song(client, room, 1)
    assert response.status_code == 201
    entry = response.json()["entry"]
    assert entry["state"] == "requested"
    assert entry["position"] is None
    assert entry["score"] == 1
    assert entry["my_vote"] == 1
    assert entry["playable"] is True
    assert entry["added_by"] == GUEST
    assert entry["added_by_name"] == f"user{GUEST}"
    assert entry["song"]["id"] == 1
    assert (room, {"topic": "queue", "type": "requested", "entry_id": entry["id"]}) in published
    check_invariants(room)


def test_request_needs_login(client, room):
    client.cookies.clear()
    assert client.post(f"/room/{room}/queue/request", json={"query": "https://x?v=1"}).status_code == 403


def test_request_empty_query_is_422(client, room):
    as_user(client, GUEST)
    assert client.post(f"/room/{room}/queue/request", json={"query": ""}).status_code == 422


def test_request_unknown_room_is_404(client, services):
    assert request_song(client, 999, 1).status_code == 404


def test_request_same_song_twice_gives_same_entry(client, room):
    first = add_requested(client, room, 1, GUEST)
    second = add_requested(client, room, 1, OTHER)
    assert first == second
    assert len(by_id(room)) == 1
    assert queue_of(client, room)["pending"][0]["score"] == 2


def test_request_banned_song_is_409(client, room):
    host_put(client, f"/room/{room}/queue/ban/1")
    assert request_song(client, room, 1).status_code == 409
    assert by_id(room) == {}


def test_request_played_song_goes_back_to_end_of_order(client, room):
    a = add_queued(client, room, 1)
    b = add_queued(client, room, 2)
    host_put(client, f"/room/{room}/queue/next")  # a plays
    host_put(client, f"/room/{room}/queue/next")  # a played, b plays
    assert by_id(room)[a].state == "played"

    assert add_requested(client, room, 1) == a
    assert by_id(room)[a].state == "queued"
    assert order(room) == [b, a]
    check_invariants(room)


def test_get_queue_shape(client, room):
    add_queued(client, room, 1)
    add_requested(client, room, 2)
    host_put(client, f"/room/{room}/queue/ban/3")
    body = queue_of(client, room)
    assert set(body) == {"order", "pending", "history", "banned"}
    assert [e["song_id"] for e in body["order"]] == [1]
    assert [e["song_id"] for e in body["pending"]] == [2]
    assert body["history"] == []
    assert body["banned"] == [3]


def test_get_queue_unknown_room_is_404(client, services):
    as_user(client, GUEST)
    assert client.get("/room/999/queue").status_code == 404


# --- accept ---


def test_accept_appends_to_order(client, room, published):
    a = add_queued(client, room, 1)
    b = add_requested(client, room, 2)
    response = host_put(client, f"/room/{room}/queue/temp_accept/{b}")
    assert response.status_code == 200
    assert response.json()["entry"]["state"] == "queued"
    assert order(room) == [a, b]
    assert (room, {"topic": "queue", "type": "accepted", "entry_id": b}) in published
    check_invariants(room)


def test_accept_twice_is_409(client, room):
    a = add_queued(client, room, 1)
    assert host_put(client, f"/room/{room}/queue/temp_accept/{a}").status_code == 409


def test_accept_unknown_entry_is_404(client, room):
    assert host_put(client, f"/room/{room}/queue/temp_accept/999").status_code == 404


def test_accept_entry_of_other_room_is_404(client, services):
    room_a = create_room(client, "a")
    room_b = create_room(client, "b")
    entry = add_requested(client, room_a, 1)
    assert host_put(client, f"/room/{room_b}/queue/temp_accept/{entry}").status_code == 404


# --- move ---


@pytest.fixture
def three(client, room) -> list[int]:
    return [add_queued(client, room, song) for song in (1, 2, 3)]


@pytest.mark.parametrize(
    ("index", "position", "expected"),
    [
        (2, 0, [2, 0, 1]),
        (0, 1, [1, 0, 2]),
        (0, 2, [1, 2, 0]),
        (0, 99, [1, 2, 0]),  # past the end clamps to the last slot
        (1, 1, [0, 1, 2]),
    ],
)
def test_move(client, room, three, index, position, expected):
    response = host_put(client, f"/room/{room}/queue/move/{three[index]}", json={"position": position})
    assert response.status_code == 200
    assert order(room) == [three[i] for i in expected]
    check_invariants(room)


def test_move_negative_position_is_422(client, room, three):
    assert host_put(client, f"/room/{room}/queue/move/{three[0]}", json={"position": -1}).status_code == 422


def test_move_requested_entry_is_409(client, room, three):
    pending = add_requested(client, room, 9)
    assert host_put(client, f"/room/{room}/queue/move/{pending}", json={"position": 0}).status_code == 409


def test_move_unknown_entry_is_404(client, room, three):
    assert host_put(client, f"/room/{room}/queue/move/999", json={"position": 0}).status_code == 404


# --- next ---


def test_next_starts_first_entry(client, room, three):
    response = host_put(client, f"/room/{room}/queue/next")
    assert response.status_code == 200
    entry = by_id(room)[three[0]]
    assert entry.state == "playing"
    assert entry.position == 0
    assert entry.played_at is not None
    check_invariants(room)


def test_next_moves_current_to_history(client, room, three):
    host_put(client, f"/room/{room}/queue/next")
    host_put(client, f"/room/{room}/queue/next")
    rows = by_id(room)
    assert rows[three[0]].state == "played"
    assert rows[three[1]].state == "playing"
    assert order(room) == [three[1], three[2]]
    history = queue_of(client, room)["history"]
    assert [e["id"] for e in history] == [three[0]]
    check_invariants(room)


def test_next_with_amount_skips_entries(client, room, three):
    host_put(client, f"/room/{room}/queue/next")  # 0 plays
    assert host_put(client, f"/room/{room}/queue/next", params={"amount": 2}).status_code == 200
    rows = by_id(room)
    assert rows[three[2]].state == "playing"
    assert rows[three[1]].state == "queued"  # skipped, never played
    assert rows[three[0]].state == "played"
    check_invariants(room)


def test_next_past_end_is_409(client, room, three):
    host_put(client, f"/room/{room}/queue/next")
    assert host_put(client, f"/room/{room}/queue/next", params={"amount": 3}).status_code == 409
    assert by_id(room)[three[0]].state == "playing"


def test_next_on_empty_queue_is_409(client, room):
    assert host_put(client, f"/room/{room}/queue/next").status_code == 409


def test_next_amount_zero_is_422(client, room, three):
    assert host_put(client, f"/room/{room}/queue/next", params={"amount": 0}).status_code == 422


def test_next_entry_without_upvote_is_409(client, room):
    a = add_queued(client, room, 1)
    as_user(client, GUEST)
    client.put(f"/room/{room}/queue/vote/{a}", params={"direction": "down"})
    assert host_put(client, f"/room/{room}/queue/next").status_code == 409
    assert by_id(room)[a].state == "queued"


# --- toggle ---


def test_toggle_nothing_playing_is_409(client, room, three):
    assert host_put(client, f"/room/{room}/queue/toggle").status_code == 409


def test_toggle_flips_playing_and_paused(client, room, three):
    host_put(client, f"/room/{room}/queue/next")
    response = host_put(client, f"/room/{room}/queue/toggle")
    assert response.json()["entry"]["state"] == "paused"
    check_invariants(room)
    response = host_put(client, f"/room/{room}/queue/toggle")
    assert response.json()["entry"]["state"] == "playing"
    check_invariants(room)


@pytest.fixture
def paused(client, room, three) -> list[int]:
    """three[0] is paused, three[1] and three[2] wait."""
    host_put(client, f"/room/{room}/queue/next")
    host_put(client, f"/room/{room}/queue/toggle")
    assert by_id(room)[three[0]].state == "paused"
    return three


def test_accept_while_paused(client, room, paused):
    entry = add_requested(client, room, 9)
    assert host_put(client, f"/room/{room}/queue/temp_accept/{entry}").status_code == 200
    check_invariants(room)


def test_move_while_paused(client, room, paused):
    assert host_put(client, f"/room/{room}/queue/move/{paused[2]}", json={"position": 1}).status_code == 200
    check_invariants(room)


def test_next_while_paused_plays_next_entry(client, room, paused):
    assert host_put(client, f"/room/{room}/queue/next").status_code == 200
    rows = by_id(room)
    assert rows[paused[0]].state == "played"
    assert rows[paused[1]].state == "playing"
    check_invariants(room)


def test_ban_while_paused(client, room, paused):
    banned_song = by_id(room)[paused[1]].song_id
    assert host_put(client, f"/room/{room}/queue/ban/{banned_song}").status_code == 200
    check_invariants(room)


def test_remove_while_paused(client, room, paused):
    as_user(client, HOST)
    assert client.delete(f"/room/{room}/queue/item/{paused[1]}").status_code == 200
    check_invariants(room)


# --- prev ---


def test_prev_restores_last_played(client, room, three):
    host_put(client, f"/room/{room}/queue/next")  # 0 plays
    host_put(client, f"/room/{room}/queue/next")  # 0 played, 1 plays
    response = host_put(client, f"/room/{room}/queue/prev")
    assert response.status_code == 200
    rows = by_id(room)
    assert rows[three[0]].state == "playing"
    assert rows[three[1]].state == "played"
    assert order(room)[0] == three[0]
    check_invariants(room)


def test_prev_without_history_is_409(client, room, three):
    host_put(client, f"/room/{room}/queue/next")
    assert host_put(client, f"/room/{room}/queue/prev").status_code == 409
    assert by_id(room)[three[0]].state == "playing"


def test_prev_amount_past_history_is_409(client, room, three):
    host_put(client, f"/room/{room}/queue/next")
    host_put(client, f"/room/{room}/queue/next")
    assert host_put(client, f"/room/{room}/queue/prev", params={"amount": 5}).status_code == 409


# --- ban / unban / remove ---


def test_ban_removes_entries_and_renumbers(client, room, three, published):
    song = by_id(room)[three[1]].song_id
    assert host_put(client, f"/room/{room}/queue/ban/{song}").status_code == 200
    assert order(room) == [three[0], three[2]]
    assert (room, {"topic": "queue", "type": "banned", "song_id": song}) in published
    check_invariants(room)


def test_ban_twice_is_handled(client, room):
    host_put(client, f"/room/{room}/queue/ban/1")
    assert host_put(client, f"/room/{room}/queue/ban/1").status_code < 500


def test_unban_allows_request_again(client, room):
    host_put(client, f"/room/{room}/queue/ban/1")
    as_user(client, HOST)
    assert client.delete(f"/room/{room}/queue/ban/1").status_code == 200
    assert request_song(client, room, 1).status_code == 201


def test_unban_song_not_banned_is_ok(client, room):
    as_user(client, HOST)
    assert client.delete(f"/room/{room}/queue/ban/1").status_code == 200


def test_remove_entry_renumbers(client, room, three, published):
    as_user(client, HOST)
    assert client.delete(f"/room/{room}/queue/item/{three[0]}").status_code == 200
    assert order(room) == [three[1], three[2]]
    assert (room, {"topic": "queue", "type": "deleted", "entry_id": three[0]}) in published
    check_invariants(room)


def test_removed_song_can_be_requested_again(client, room, three):
    song = by_id(room)[three[0]].song_id
    as_user(client, HOST)
    client.delete(f"/room/{room}/queue/item/{three[0]}")
    assert request_song(client, room, song).status_code == 201


def test_remove_unknown_entry_is_404(client, room):
    as_user(client, HOST)
    assert client.delete(f"/room/{room}/queue/item/999").status_code == 404


# --- host only ---


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "/room/{room}/queue/move/{entry}", {"position": 0}),
        ("put", "/room/{room}/queue/ban/1", None),
        ("delete", "/room/{room}/queue/ban/1", None),
        ("put", "/room/{room}/queue/temp_accept/{entry}", None),
        ("put", "/room/{room}/queue/toggle", None),
        ("put", "/room/{room}/queue/next", None),
        ("put", "/room/{room}/queue/prev", None),
        ("delete", "/room/{room}/queue/item/{entry}", None),
    ],
)
def test_host_routes_refuse_guest(client, room, method, path, body):
    entry = add_requested(client, room, 5)
    before = {e.id: (e.state, e.position) for e in by_id(room).values()}
    as_user(client, GUEST)
    url = path.format(room=room, entry=entry)
    kwargs = {"json": body} if body is not None else {}
    assert client.request(method.upper(), url, **kwargs).status_code == 403
    assert {e.id: (e.state, e.position) for e in by_id(room).values()} == before


@pytest.mark.parametrize("path", ["/room/999/queue/toggle", "/room/999/queue/next", "/room/999/queue/ban/1"])
def test_host_routes_unknown_room_is_404(client, services, path):
    assert host_put(client, path).status_code == 404
