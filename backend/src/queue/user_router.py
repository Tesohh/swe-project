"""User side of the queue: the queue read, requests, and votes."""

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import select

import src.auth
import src.db
from src.events import events
from src.models import RoomBan
from src.queue.order import (
    banned,
    clear_vote,
    history_of,
    order_of,
    request_entry,
    required_id,
    room_or_404,
    set_vote,
)
from src.queue.payload import build_entries, pending_of, single_payload
from src.song.download import download_song

router = APIRouter(prefix="/room")

# every queue route is nested under its room, because a room owns one queue


class RequestBody(BaseModel):
    query: str = Field(min_length=1)  # url of the song, a search text comes later


@router.get("/{room_id}/queue")
def get_queue(session: src.db.SessionDep, user: src.auth.UserDep, room_id: int):
    """The play order, the requests that wait for the audio model, the history, and the banlist of room_id."""
    room_or_404(session, room_id)
    banned_songs = session.exec(select(RoomBan).where(RoomBan.room_id == room_id)).all()
    return JSONResponse(
        {
            "order": build_entries(session, order_of(session, room_id), user),
            "pending": build_entries(session, pending_of(session, room_id), user),
            "history": build_entries(session, history_of(session, room_id), user),
            "banned": [row.song_id for row in banned_songs],
        }
    )


@router.post("/{room_id}/queue/request")
def request_song(
    session: src.db.SessionDep,
    user: src.auth.UserDep,
    room_id: int,
    body: RequestBody,
):
    """Adds a requested entry for the song that query names, voted up by user."""
    room = room_or_404(session, room_id)
    song = download_song(session, body.query)
    song_id = required_id(song.id, "song")

    if banned(session, room_id, song_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Song is banned in this room")

    # the audio model gate goes here: a song whose quality is not good never reaches the queue
    entry = request_entry(session, room, song_id, user)
    entry_id = required_id(entry.id, "queue entry")
    set_vote(session, room_id, entry_id, user, 1)

    events.publish(room_id, {"topic": "queue", "type": "requested", "entry_id": entry_id})
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"status": "ok", "entry": single_payload(session, room_id, entry_id, user)},
    )


@router.put("/{room_id}/queue/vote/{item_id}")
def vote_entry(
    session: src.db.SessionDep,
    user: src.auth.UserDep,
    room_id: int,
    item_id: int,
    direction: Literal["up", "down"] = "up",
):
    """Votes entry item_id for user. direction up stores +1, direction down stores -1."""
    room_or_404(session, room_id)
    weight = 1 if direction == "up" else -1
    set_vote(session, room_id, item_id, user, weight)
    events.publish(room_id, {"topic": "queue", "type": "voted", "entry_id": item_id, "weight": weight})
    return JSONResponse({"status": "ok", "entry": single_payload(session, room_id, item_id, user)})


@router.delete("/{room_id}/queue/vote/{item_id}")
def vote_clear(session: src.db.SessionDep, user: src.auth.UserDep, room_id: int, item_id: int):
    """Removes the vote of user on entry item_id, so the entry scores 0."""
    room_or_404(session, room_id)
    clear_vote(session, room_id, item_id, user)
    events.publish(room_id, {"topic": "queue", "type": "unvoted", "entry_id": item_id})
    return JSONResponse({"status": "ok", "entry": single_payload(session, room_id, item_id, user)})
