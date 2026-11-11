import asyncio
from collections.abc import AsyncIterable

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlmodel import select

import src.auth
import src.db
import src.models
from src.events import events
from src.models import Room
from src.queue.order import required_id

router = APIRouter(prefix="/room")


class CreateRoomBody(BaseModel):
    name: str
    password: str | None = None
    description: str | None = None


@router.post("/create")
def create_room(
    session: src.db.SessionDep,
    user: src.auth.UserDep,
    body: CreateRoomBody,
):
    existing = session.exec(select(src.models.Room).where(src.models.Room.name == body.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Room already exists")

    room = src.models.Room(
        name=body.name,
        user_id=required_id(user.id, "user"),
        password_hash=src.auth.get_password_hash(body.password) if body.password else None,
        description=body.description,
    )
    session.add(room)
    session.commit()
    session.refresh(room)

    return JSONResponse(status_code=status.HTTP_201_CREATED, content={"status": "ok", "room_id": room.id})


def get_owned_room(session: src.db.SessionDep, room_id: int, user: src.auth.UserDep) -> src.models.Room:
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


@router.put("/edit/{room_id}")
def edit_room(session: src.db.SessionDep, user: src.auth.UserDep, room_id: int, body: EditRoomBody):
    room = get_owned_room(session, room_id, user)

    if body.name is not None and body.name != room.name:
        clash = session.exec(select(src.models.Room).where(src.models.Room.name == body.name)).first()
        if clash:
            raise HTTPException(status_code=409, detail="Room already exists")
        room.name = body.name

    if body.password is not None:
        room.password_hash = src.auth.get_password_hash(body.password)

    if body.description is not None:
        room.description = body.description

    session.add(room)
    session.commit()
    session.refresh(room)
    events.publish(room_id, {"topic": "room", "type": "edited"})
    return JSONResponse(status_code=200, content={"status": "ok", "room_id": room.id})


@router.delete("/delete/{room_id}")
def delete_room(session: src.db.SessionDep, user: src.auth.UserDep, room_id: int):
    room = get_owned_room(session, room_id, user)
    session.delete(room)
    session.commit()
    events.publish(room_id, {"topic": "room", "type": "deleted"})
    return JSONResponse(status_code=200, content={"status": "ok"})


@router.get("/mine")
def get_my_rooms(user: src.auth.UserDep, session: src.db.SessionDep):
    rooms = session.exec(select(Room).where(Room.user_id == user.id)).all()

    return JSONResponse(
        [
            {
                "id": room.id,
                "name": room.name,
                "user_id": room.user_id,
                "description": room.description,
                "is_password_protected": room.password_hash is not None,
            }
            for room in rooms
        ]
    )


@router.get("/{room_id}/events", response_class=EventSourceResponse)
async def stream_room_events(room_id: int) -> AsyncIterable[ServerSentEvent]:
    """Streams the changes of room_id, which holds the one queue of that room."""
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


@router.get("/{room_id}")
def get_room(session: src.db.SessionDep, room_id: int):
    room = session.get(src.models.Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return JSONResponse(
        {
            "id": room.id,
            "name": room.name,
            "user_id": room.user_id,
            "description": room.description,
            "is_password_protected": room.password_hash is not None,
        }
    )
