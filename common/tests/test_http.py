import httpx
import pytest
import respx
from fastapi import HTTPException

from common.http import base_url, call

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


URL = "http://other:8000/internal/thing"


async def _error(**kwargs) -> HTTPException:
    with pytest.raises(HTTPException) as err:
        await call("other", "GET", URL, **kwargs)
    return err.value


@respx.mock
async def test_success_returns_response():
    respx.get(URL).respond(200, json={"ok": True})
    response = await call("other", "GET", URL)
    assert response.json() == {"ok": True}


@respx.mock
async def test_kwargs_reach_the_request():
    route = respx.post(URL).respond(200)
    await call("other", "POST", URL, json={"a": 1}, params={"ids": [1, 2]})
    request = route.calls.last.request
    assert request.url.params.get_list("ids") == ["1", "2"]
    assert request.content == b'{"a":1}'


@respx.mock
async def test_connection_error_is_502():
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    err = await _error()
    assert err.status_code == 502
    assert "other" in err.detail


@respx.mock
async def test_timeout_is_502():
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert (await _error()).status_code == 502


@respx.mock
@pytest.mark.parametrize("code", [500, 503])
async def test_5xx_is_502(code):
    respx.get(URL).respond(code, text="boom")
    assert (await _error()).status_code == 502


@respx.mock
async def test_4xx_keeps_status_and_detail():
    respx.get(URL).respond(404, json={"detail": "No song with id 3"})
    err = await _error()
    assert err.status_code == 404
    assert err.detail == "No song with id 3"


@respx.mock
async def test_4xx_with_text_body_keeps_text():
    respx.get(URL).respond(422, text="plain text")
    err = await _error()
    assert err.status_code == 422
    assert err.detail == "plain text"


def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("OTHER_BASE", "http://x:1/")
    assert base_url("OTHER_BASE", "http://default") == "http://x:1"


def test_base_url_default(monkeypatch):
    monkeypatch.delenv("OTHER_BASE", raising=False)
    assert base_url("OTHER_BASE", "http://default/") == "http://default"
