import httpx
import respx
from common.auth import TOKEN_COOKIE, verify_password
from sqlmodel import select

from src.models import User
from tests.conftest import token_for

QUEUES_DELETE = "http://queues:8000/internal/users/{id}"


def signup(client, name="alice", password="pw1"):
    return client.post("/api/auth/signup", json={"username": name, "password": password})


def login(client, name="alice", password="pw1"):
    return client.post("/api/auth/token", data={"username": name, "password": password})


def signed_in(client, name="alice", password="pw1") -> int:
    user_id = signup(client, name, password).json()["id"]
    assert login(client, name, password).status_code == 200
    return user_id


def test_signup_then_login_then_me(client):
    response = signup(client)
    assert response.status_code == 200
    assert response.json()["name"] == "alice"

    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert f"{TOKEN_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/api" in cookie
    assert "Secure" in cookie

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["name"] == "alice"


def test_password_is_stored_hashed(client, session):
    signup(client, password="secret")
    user = session.exec(select(User)).one()
    assert user.password_hash != "secret"
    assert verify_password("secret", user.password_hash)


def test_signup_does_not_leak_password_hash(client):
    assert "password_hash" not in signup(client).json()


def test_me_does_not_leak_password_hash(client):
    signed_in(client)
    assert "password_hash" not in client.get("/api/auth/me").json()


def test_duplicate_signup_is_refused(client):
    signup(client)
    assert signup(client).status_code >= 400


def test_duplicate_signup_is_409(client):
    signup(client)
    assert signup(client).status_code == 409


def test_wrong_password_is_401(client):
    signup(client)
    assert login(client, password="wrong").status_code == 401


def test_unknown_user_is_401(client):
    assert login(client, name="nobody").status_code == 401


def test_me_without_cookie_is_403(client):
    assert client.get("/api/auth/me").status_code == 403


def test_token_of_missing_user_is_401(login):
    client = login(999)
    assert client.get("/api/auth/me").status_code == 401


def test_logout_deletes_cookie(client):
    signed_in(client)
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert f'{TOKEN_COOKIE}=""' in response.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 403


def test_change_password(client):
    signed_in(client)
    response = client.post("/api/auth/change_password", json={"old_password": "pw1", "new_password": "pw2"})
    assert response.status_code == 200
    assert login(client, password="pw1").status_code == 401
    assert login(client, password="pw2").status_code == 200


def test_change_password_wrong_old_is_401(client):
    signed_in(client)
    response = client.post("/api/auth/change_password", json={"old_password": "bad", "new_password": "pw2"})
    assert response.status_code == 401
    assert login(client, password="pw1").status_code == 200


def test_change_username(client):
    signed_in(client)
    response = client.post("/api/auth/change_username", json={"new_username": "bob"})
    assert response.status_code == 200
    assert client.get("/api/auth/me").json()["name"] == "bob"
    assert login(client, name="bob").status_code == 200
    assert login(client, name="alice").status_code == 401


def test_change_username_to_taken_name_is_refused(client):
    signup(client, name="bob")
    signed_in(client)
    response = client.post("/api/auth/change_username", json={"new_username": "bob"})
    assert response.status_code >= 400
    assert client.get("/api/auth/me").json()["name"] == "alice"


@respx.mock
def test_delete_account_calls_queues_then_deletes(client, session):
    user_id = signed_in(client)
    route = respx.delete(QUEUES_DELETE.format(id=user_id)).respond(200, json={"status": "ok"})

    assert client.post("/api/auth/delete").status_code == 200
    assert route.called
    assert session.get(User, user_id) is None


@respx.mock
def test_delete_account_keeps_user_when_queues_fails(client, session):
    user_id = signed_in(client)
    respx.delete(QUEUES_DELETE.format(id=user_id)).respond(500)

    assert client.post("/api/auth/delete").status_code == 502
    assert session.get(User, user_id) is not None


@respx.mock
def test_delete_account_keeps_user_when_queues_is_down(client, session):
    user_id = signed_in(client)
    respx.delete(QUEUES_DELETE.format(id=user_id)).mock(side_effect=httpx.ConnectError("down"))

    assert client.post("/api/auth/delete").status_code == 502
    assert session.get(User, user_id) is not None


@respx.mock
def test_deleted_user_token_no_longer_works(client):
    user_id = signed_in(client)
    respx.delete(QUEUES_DELETE.format(id=user_id)).respond(200, json={})
    client.post("/api/auth/delete")
    client.cookies.set(TOKEN_COOKIE, token_for(user_id))
    assert client.get("/api/auth/me").status_code == 401


def test_internal_names(client):
    a = signup(client, name="alice").json()["id"]
    b = signup(client, name="bob").json()["id"]
    response = client.get("/internal/users/names", params={"ids": [a, b, 999]})
    assert response.status_code == 200
    assert response.json() == {str(a): "alice", str(b): "bob"}


def test_internal_names_without_ids(client):
    assert client.get("/internal/users/names").json() == {}


def test_internal_names_contract(client):
    """queues reads this as a dict of user id -> name (src/users.py)."""
    a = signup(client, name="alice").json()["id"]
    body = client.get("/internal/users/names", params={"ids": [a]}).json()
    assert {int(key): value for key, value in body.items()} == {a: "alice"}
