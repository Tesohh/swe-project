import asyncio
from collections.abc import AsyncIterable

from common.auth import CurrentUserDep, get_password_hash
from common.schemas import Status, errors
from fastapi import APIRouter, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlmodel import select

import src.db
import src.models
from src.events import events
from src.models import Room
from src.queue.order import required_id
from src.schemas import RoomCreated, RoomPublic

router = APIRouter(prefix="/room")


class CreateRoomBody(BaseModel):
    name: str
    password: str | None = None
    description: str | None = None


@router.post("/create", status_code=status.HTTP_201_CREATED, responses=errors(401, 409))
def create_room(
    session: src.db.SessionDep,
    user: CurrentUserDep,
    body: CreateRoomBody,
) -> RoomCreated:
    """Creates a room that user hosts. The name must be new. A password is optional."""
    existing = session.exec(select(src.models.Room).where(src.models.Room.name == body.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Room already exists")

    room = src.models.Room(
        name=body.name,
        user_id=required_id(user.id, "user"),
        password_hash=get_password_hash(body.password) if body.password else None,
        description=body.description,
    )
    session.add(room)
    session.commit()
    session.refresh(room)

    return RoomCreated(room_id=room.id)


def room_public(room: Room) -> RoomPublic:
    """The fields of a room that a client sees. The password hash stays here."""
    return RoomPublic(
        id=room.id,
        name=room.name,
        user_id=room.user_id,
        description=room.description,
        is_password_protected=room.password_hash is not None,
    )


def get_owned_room(session: src.db.SessionDep, room_id: int, user: CurrentUserDep) -> src.models.Room:
    room = session.get(src.models.Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if room.user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the host can manage this room")
    return room


class EditRoomBody(BaseModel):
    name: str | None = None
    password: str | None = None
    description: str | None = None


@router.put("/edit/{room_id}", responses=errors(401, 403, 404, 409))
def edit_room(session: src.db.SessionDep, user: CurrentUserDep, room_id: int, body: EditRoomBody) -> RoomCreated:
    """Changes the name, password or description of room_id, host only. A field that is not sent stays the same."""
    room = get_owned_room(session, room_id, user)

    if body.name is not None and body.name != room.name:
        clash = session.exec(select(src.models.Room).where(src.models.Room.name == body.name)).first()
        if clash:
            raise HTTPException(status_code=409, detail="Room already exists")
        room.name = body.name

    if body.password is not None:
        room.password_hash = get_password_hash(body.password)

    if body.description is not None:
        room.description = body.description

    session.add(room)
    session.commit()
    session.refresh(room)
    events.publish(room_id, {"topic": "room", "type": "edited"})
    return RoomCreated(room_id=room.id)


@router.delete("/delete/{room_id}", responses=errors(401, 403, 404))
def delete_room(session: src.db.SessionDep, user: CurrentUserDep, room_id: int) -> Status:
    """Deletes room_id with its queue, votes and bans, host only."""
    room = get_owned_room(session, room_id, user)
    session.delete(room)
    session.commit()
    events.publish(room_id, {"topic": "room", "type": "deleted"})
    return Status()


@router.get("/mine", responses=errors(401))
def get_my_rooms(user: CurrentUserDep, session: src.db.SessionDep) -> list[RoomPublic]:
    """The rooms that user hosts."""
    rooms = session.exec(select(Room).where(Room.user_id == user.id)).all()

    return [room_public(room) for room in rooms]


@router.get("/{room_id}/events", response_class=EventSourceResponse)
async def stream_room_events(room_id: int) -> AsyncIterable[ServerSentEvent]:
    """Streams the changes of room_id (server-sent events), which holds the one queue of that room.

    Each event has `event` set to its topic and a JSON `data` with `topic`, `type`, and for queue events an `entry_id`.
    - room: `edited`, `deleted`, or `missing` (room_id does not exist, and the stream ends).
    - queue: `requested`, `accepted`, `ordered`, `playing`, `paused`, `deleted`, `voted` (with `weight`), `unvoted`,
      `banned` and `unbanned` (with `song_id`).
    A comment `ping` is sent every 30 seconds to keep the connection open.
    """
    with src.db.Session(src.db.engine) as session:
        if session.get(Room, room_id) is None:
            yield ServerSentEvent(data={"topic": "room", "type": "missing"}, event="room")
            return

    queue = events.subscribe(room_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
            except TimeoutError:
                yield ServerSentEvent(comment="ping")
                continue
            yield ServerSentEvent(data=event, event=event["topic"])
    finally:
        events.unsubscribe(room_id, queue)


@router.get("/{room_id}", responses=errors(404))
def get_room(session: src.db.SessionDep, room_id: int) -> RoomPublic:
    """The public fields of room_id."""
    room = session.get(src.models.Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return room_public(room)
