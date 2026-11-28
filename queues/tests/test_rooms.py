from sqlmodel import select

from src.models import QueueItem, RoomBan, Vote
from tests.conftest import GUEST, HOST
from tests.helpers import add_queued, as_user, create_room, host_put


def test_create_room_needs_login(client):
    assert client.post("/room/create", json={"name": "x"}).status_code == 403


def test_create_and_get_room(client):
    room_id = create_room(client, description="chill only")
    response = client.get(f"/room/{room_id}")
    assert response.status_code == 200
    assert response.json() == {
        "id": room_id,
        "name": "beach",
        "user_id": HOST,
        "description": "chill only",
        "is_password_protected": False,
    }


def test_room_with_password_is_protected(client):
    room_id = create_room(client, password="pw")
    assert client.get(f"/room/{room_id}").json()["is_password_protected"] is True


def test_duplicate_room_name_is_409(client):
    create_room(client)
    as_user(client, GUEST)
    assert client.post("/room/create", json={"name": "beach"}).status_code == 409


def test_unknown_room_is_404(client):
    assert client.get("/room/999").status_code == 404


def test_mine_lists_only_own_rooms(client):
    create_room(client, "a", host=HOST)
    create_room(client, "b", host=GUEST)
    as_user(client, HOST)
    names = [room["name"] for room in client.get("/room/mine").json()]
    assert names == ["a"]


def test_edit_room(client, published):
    room_id = create_room(client)
    response = host_put(client, f"/room/edit/{room_id}", json={"name": "bar", "description": "d", "password": "pw"})
    assert response.status_code == 200
    room = client.get(f"/room/{room_id}").json()
    assert room["name"] == "bar"
    assert room["description"] == "d"
    assert room["is_password_protected"] is True
    assert (room_id, {"topic": "room", "type": "edited"}) in published


def test_edit_by_guest_is_403(client):
    room_id = create_room(client)
    as_user(client, GUEST)
    assert client.put(f"/room/edit/{room_id}", json={"name": "x"}).status_code == 403


def test_edit_unknown_room_is_404(client):
    as_user(client, HOST)
    assert client.put("/room/edit/999", json={"name": "x"}).status_code == 404


def test_rename_to_taken_name_is_409(client):
    create_room(client, "taken")
    room_id = create_room(client, "mine")
    assert host_put(client, f"/room/edit/{room_id}", json={"name": "taken"}).status_code == 409


def test_rename_to_same_name_is_ok(client):
    room_id = create_room(client)
    assert host_put(client, f"/room/edit/{room_id}", json={"name": "beach"}).status_code == 200


def test_delete_by_guest_is_403(client):
    room_id = create_room(client)
    as_user(client, GUEST)
    assert client.delete(f"/room/delete/{room_id}").status_code == 403
    assert client.get(f"/room/{room_id}").status_code == 200


def test_delete_room_cascades(client, services, session, published):
    room_id = create_room(client)
    add_queued(client, room_id, 1)
    host_put(client, f"/room/{room_id}/queue/ban/2")

    as_user(client, HOST)
    assert client.delete(f"/room/delete/{room_id}").status_code == 200
    assert client.get(f"/room/{room_id}").status_code == 404
    assert session.exec(select(QueueItem)).all() == []
    assert session.exec(select(Vote)).all() == []
    assert session.exec(select(RoomBan)).all() == []
    assert (room_id, {"topic": "room", "type": "deleted"}) in published
