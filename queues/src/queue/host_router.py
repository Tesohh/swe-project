"""Host side of the queue: order moves, banlist, player controls, entry removal, and the temporary accept."""

from common.auth import CurrentUserDep
from common.schemas import Status, errors
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

import src.db
from src.events import events
from src.queue.order import (
    accept_entry,
    ban,
    move,
    owned_room,
    play_next,
    play_prev,
    remove_entry,
    required_id,
    toggle_player,
    unban,
)
from src.queue.payload import single_payload
from src.schemas import EntryResponse

router = APIRouter(prefix="/room")


class MoveBody(BaseModel):
    position: int = Field(ge=0)


@router.put("/{room_id}/queue/move/{item_id}", responses=errors(401, 403, 404, 409, 502))
def move_entry(session: src.db.SessionDep, user: CurrentUserDep, room_id: int, item_id: int, body: MoveBody) -> EntryResponse:
    """Moves entry item_id to position, host only."""
    owned_room(session, room_id, user)
    move(session, room_id, item_id, body.position)
    events.publish(room_id, {"topic": "queue", "type": "ordered", "entry_id": item_id})
    return EntryResponse(entry=single_payload(session, room_id, item_id, user))


@router.put("/{room_id}/queue/ban/{song_id}", responses=errors(401, 403, 404, 409, 502))
def ban_song(session: src.db.SessionDep, user: CurrentUserDep, room_id: int, song_id: int) -> Status:
    """Adds song_id to the banlist of room_id and drops its entries from the queue, host only."""
    owned_room(session, room_id, user)
    ban(session, room_id, song_id)
    events.publish(room_id, {"topic": "queue", "type": "banned", "song_id": song_id})
    return Status()


@router.delete("/{room_id}/queue/ban/{song_id}", responses=errors(401, 403, 404, 409, 502))
def unban_song(session: src.db.SessionDep, user: CurrentUserDep, room_id: int, song_id: int) -> Status:
    """Lifts the ban of song_id in room_id, host only."""
    owned_room(session, room_id, user)
    unban(session, room_id, song_id)
    events.publish(room_id, {"topic": "queue", "type": "unbanned", "song_id": song_id})
    return Status()


@router.put("/{room_id}/queue/temp_accept/{item_id}", responses=errors(401, 403, 404, 409, 502))
def temp_accept_entry(session: src.db.SessionDep, user: CurrentUserDep, room_id: int, item_id: int) -> EntryResponse:
    """Temporary stand-in for the audio gate: moves a requested entry into the order, host only.
    Delete this route when admission runs.
    """
    owned_room(session, room_id, user)
    entry = accept_entry(session, room_id, item_id)
    entry_id = required_id(entry.id, "queue entry")
    events.publish(room_id, {"topic": "queue", "type": "accepted", "entry_id": entry_id})
    return EntryResponse(entry=single_payload(session, room_id, entry_id, user))


@router.put("/{room_id}/queue/toggle", responses=errors(401, 403, 404, 409, 502))
def toggle_player_route(session: src.db.SessionDep, user: CurrentUserDep, room_id: int) -> EntryResponse:
    """Flips the track that plays between playing and paused, host only."""
    owned_room(session, room_id, user)
    current = toggle_player(session, room_id)
    events.publish(room_id, {"topic": "queue", "type": current.state, "entry_id": current.id})
    payload = single_payload(session, room_id, required_id(current.id, "queue entry"), user)
    return EntryResponse(entry=payload)


@router.put("/{room_id}/queue/next", responses=errors(401, 403, 404, 409, 502))
def play_next_entry(
    session: src.db.SessionDep,
    user: CurrentUserDep,
    room_id: int,
    amount: int = Query(default=1, ge=1),
) -> EntryResponse:
    """Ends the track that plays and starts the entry amount places ahead in the order, host only."""
    owned_room(session, room_id, user)
    entry = play_next(session, room_id, amount)
    entry_id = required_id(entry.id, "queue entry")
    events.publish(room_id, {"topic": "queue", "type": "playing", "entry_id": entry_id})
    return EntryResponse(entry=single_payload(session, room_id, entry_id, user))


@router.put("/{room_id}/queue/prev", responses=errors(401, 403, 404, 409, 502))
def play_prev_entry(
    session: src.db.SessionDep,
    user: CurrentUserDep,
    room_id: int,
    amount: int = Query(default=1, ge=1),
) -> EntryResponse:
    """Ends the track that plays and starts the track played amount tracks before it, host only."""
    owned_room(session, room_id, user)
    entry = play_prev(session, room_id, amount)
    entry_id = required_id(entry.id, "queue entry")
    events.publish(room_id, {"topic": "queue", "type": "playing", "entry_id": entry_id})
    return EntryResponse(entry=single_payload(session, room_id, entry_id, user))


@router.delete("/{room_id}/queue/item/{item_id}", responses=errors(401, 403, 404, 409, 502))
def delete_entry(session: src.db.SessionDep, user: CurrentUserDep, room_id: int, item_id: int) -> Status:
    """Deletes the queue entry item_id, host only. The song is only removed from the queue temporarily and can be added back at any time."""
    owned_room(session, room_id, user)
    remove_entry(session, room_id, item_id)
    events.publish(room_id, {"topic": "queue", "type": "deleted", "entry_id": item_id})
    return Status()
