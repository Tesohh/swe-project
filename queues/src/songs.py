"""Client of the songs service. The queues service keeps only song ids."""

from common.http import base_url, call
from fastapi import HTTPException, status


def _base() -> str:
    return base_url("SONGS_BASE", "http://songs:8000")


async def song_from_url(query: str) -> dict:
    """Payload of the song that query names. The songs service downloads it if it is new."""
    # a download can take long, so the timeout is long too
    response = await call("songs", "POST", f"{_base()}/internal/songs/from-url", json={"query": query}, timeout=300.0)
    return response.json()["song"]


async def songs_by_id(ids: list[int]) -> dict[int, dict]:
    """Song payloads by song id. A missing song is a data error, so it is a 502."""
    wanted = sorted(set(ids))
    if not wanted:
        return {}
    response = await call("songs", "GET", f"{_base()}/internal/songs", params={"ids": wanted})
    found = {song["id"]: song for song in response.json()["songs"]}
    for song_id in wanted:
        if song_id not in found:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Song {song_id} is missing")
    return found
