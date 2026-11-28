import datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from common import auth


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")


def _status(func, *args) -> int:
    with pytest.raises(auth.HTTPException) as err:
        func(*args)
    return err.value.status_code


def test_token_round_trip():
    token = auth.create_access_token({"sub": "42"})
    assert auth.user_id_from_token(token) == 42


def test_expired_token_is_401():
    token = auth.create_access_token({"sub": "1"}, expires_delta=datetime.timedelta(seconds=-1))
    assert _status(auth.user_id_from_token, token) == 401


def test_wrong_secret_is_401():
    token = jwt.encode({"sub": "1"}, "other-secret", algorithm=auth.ALGORITHM)
    assert _status(auth.user_id_from_token, token) == 401


def test_missing_sub_is_401():
    token = auth.create_access_token({"name": "x"})
    assert _status(auth.user_id_from_token, token) == 401


def test_non_int_sub_is_401():
    token = auth.create_access_token({"sub": "abc"})
    assert _status(auth.user_id_from_token, token) == 401


def test_garbage_token_is_401():
    assert _status(auth.user_id_from_token, "not-a-jwt") == 401


def test_password_hash_round_trip():
    hashed = auth.get_password_hash("hunter2")
    assert hashed != "hunter2"
    assert auth.verify_password("hunter2", hashed)
    assert not auth.verify_password("wrong", hashed)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.get("/who")
    def who(user: auth.CurrentUserDep):
        return {"id": user.id}

    @app.get("/token-only")
    def token_only(token: str = Depends(auth.oauth2_scheme)):
        return {"token": token}

    return TestClient(app)


def test_no_cookie_is_403(client):
    assert client.get("/who").status_code == 403


def test_cookie_gives_current_user(client):
    client.cookies.set(auth.TOKEN_COOKIE, auth.create_access_token({"sub": "7"}))
    response = client.get("/who")
    assert response.status_code == 200
    assert response.json() == {"id": 7}


def test_bad_cookie_is_401(client):
    client.cookies.set(auth.TOKEN_COOKIE, "bad")
    assert client.get("/who").status_code == 401


def test_bearer_header_is_not_accepted(client):
    token = auth.create_access_token({"sub": "7"})
    response = client.get("/who", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
