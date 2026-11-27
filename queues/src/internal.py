"""Routes for the other services. The gateway does not route /internal, so the browser cannot reach them."""

from fastapi import APIRouter
from sqlmodel import col, delete, select, update

import src.db
from src.events import events
from src.models import QueueItem, Room, Vote

router = APIRouter(prefix="/internal")


@router.delete("/users/{user_id}")
def delete_user_data(session: src.db.SessionDep, user_id: int):
    """Removes what a deleted user left here: the votes, the rooms they host, and their name on requests.

    The queue entries, votes and bans of a deleted room go with it (database cascade).
    """
    room_ids = list(session.exec(select(Room.id).where(Room.user_id == user_id)).all())

    session.exec(delete(Vote).where(Vote.user_id == user_id))  # type:ignore
    session.exec(update(QueueItem).where(QueueItem.added_by == user_id).values(added_by=None))  # type:ignore
    session.exec(delete(Room).where(col(Room.id).in_(room_ids)))  # type:ignore
    session.commit()

    for room_id in room_ids:
        events.publish(room_id, {"topic": "room", "type": "deleted"})
    return {"status": "ok", "rooms_deleted": len(room_ids)}
