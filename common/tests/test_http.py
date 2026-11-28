import httpx
import pytest
import respx
from fastapi import HTTPException

from common.http import base_url, call

URL = "http://other:8000/internal/thing"


def _error(**kwargs) -> HTTPException:
    with pytest.raises(HTTPException) as err:
        call("other", "GET", URL, **kwargs)
    return err.value


@respx.mock
def test_success_returns_response():
    respx.get(URL).respond(200, json={"ok": True})
    response = call("other", "GET", URL)
    assert response.json() == {"ok": True}


@respx.mock
def test_kwargs_reach_the_request():
    route = respx.post(URL).respond(200)
    call("other", "POST", URL, json={"a": 1}, params={"ids": [1, 2]})
    request = route.calls.last.request
    assert request.url.params.get_list("ids") == ["1", "2"]
    assert request.content == b'{"a":1}'


@respx.mock
def test_connection_error_is_502():
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    err = _error()
    assert err.status_code == 502
    assert "other" in err.detail


@respx.mock
def test_timeout_is_502():
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert _error().status_code == 502


@respx.mock
@pytest.mark.parametrize("code", [500, 503])
def test_5xx_is_502(code):
    respx.get(URL).respond(code, text="boom")
    assert _error().status_code == 502


@respx.mock
def test_4xx_keeps_status_and_detail():
    respx.get(URL).respond(404, json={"detail": "No song with id 3"})
    err = _error()
    assert err.status_code == 404
    assert err.detail == "No song with id 3"


@respx.mock
def test_4xx_with_text_body_keeps_text():
    respx.get(URL).respond(422, text="plain text")
    err = _error()
    assert err.status_code == 422
    assert err.detail == "plain text"


def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("OTHER_BASE", "http://x:1/")
    assert base_url("OTHER_BASE", "http://default") == "http://x:1"


def test_base_url_default(monkeypatch):
    monkeypatch.delenv("OTHER_BASE", raising=False)
    assert base_url("OTHER_BASE", "http://default/") == "http://default"
