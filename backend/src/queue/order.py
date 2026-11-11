"""Dense position order for a room queue.

Positions are integers from 0 for the queued and playing entries of one room.
Every write runs in one transaction with a row lock on the room, so two reorders
of the same room never interleave.
"""

import datetime

from fastapi import HTTPException, status
from sqlmodel import Session, col, func, select

import src.models
from src.models import QueueItem, Room, RoomBan, Vote

# temp range for positions during a renumber, so the unique check never sees a duplicate mid-flight
TEMP_OFFSET = 1_000_000

ORDERED = ("queued", "playing")


def room_or_404(session: Session, room_id: int) -> Room:
    """Room row for room_id, or 404 if the room is missing."""
    room = session.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")
    return room


def owned_room(session: Session, room_id: int, user: src.models.User) -> Room:
    """Room row that user hosts, or 403 if user is not the host."""
    room = room_or_404(session, room_id)
    if room.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the host can manage this room")
    return room


def _transaction(session: Session):
    """Closes the transaction that the dependencies opened, then opens a fresh one."""
    session.commit()
    return session.begin()


def _lock_room(session: Session, room_id: int) -> None:
    """Row lock on the room row, so writes to one room queue run one at a time."""
    session.exec(select(Room).where(Room.id == room_id).with_for_update()).first()


def entry_or_404(session: Session, room_id: int, item_id: int) -> QueueItem:
    """Queue entry item_id of room room_id, or 404 if it is not in that room."""
    entry = session.exec(
        select(QueueItem).where(QueueItem.id == item_id, QueueItem.room_id == room_id)
    ).first()
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No queue entry {item_id} in room {room_id}")
    return entry


def required_id(value: int | None, kind: str) -> int:
    """Id of a row that the db already stored, or 500 if it carries none."""
    if value is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"{kind} has no id")
    return value


def ordered_ids(session: Session, room_id: int) -> list[int]:
    """Ids of the queued and playing entries of room_id, in the current order.

    Entries with a NULL position sort last, which appends a fresh entry at the end.
    """
    # SQLModel sessions do not autoflush, so pending writes must reach the db before the read
    session.flush()
    entries = session.exec(
        select(QueueItem)
        .where(QueueItem.room_id == room_id, col(QueueItem.state).in_(ORDERED))
        .order_by(col(QueueItem.position), col(QueueItem.id))
    ).all()
    return [required_id(entry.id, "queue entry") for entry in entries]


def _renumber(session: Session, room_id: int, ids: list[int]) -> None:
    """Writes dense positions for ids, from 0 to len(ids) - 1."""
    session.flush()
    # a temp range first, so the unique check never sees a duplicate mid-flight
    entries = session.exec(
        select(QueueItem).where(QueueItem.room_id == room_id, col(QueueItem.state).in_(ORDERED))
    ).all()
    for entry in entries:
        entry.position = TEMP_OFFSET + required_id(entry.id, "queue entry")
        session.add(entry)
    session.flush()

    for position, item_id in enumerate(ids):
        entry = session.get(QueueItem, item_id)
        if entry is not None:
            entry.position = position
            session.add(entry)


def request_entry(session: Session, room: Room, song_id: int, user: src.models.User) -> QueueItem:
    """Returns the entry for song_id in room, creating it as a requested entry when it is new."""
    with _transaction(session):
        room_id = required_id(room.id, "room")
        user_id = required_id(user.id, "user")
        entry = session.exec(
            select(QueueItem).where(QueueItem.room_id == room_id, QueueItem.song_id == song_id)
        ).first()
        if entry is not None:
            if entry.state == "played":
                # the song plays again, so it returns to the order at the end
                entry.state = "queued"
                session.add(entry)
                _renumber(session, room_id, ordered_ids(session, room_id))
                session.flush()
                session.refresh(entry)
            return entry

        entry = QueueItem(
            room_id=room_id,
            song_id=song_id,
            state="requested",
            position=None,
            added_by=user_id,
        )
        session.add(entry)
        session.flush()
        session.refresh(entry)
        return entry


def banned(session: Session, room_id: int, song_id: int) -> bool:
    """True when song_id is banned in room_id."""
    return (
        session.exec(select(RoomBan).where(RoomBan.room_id == room_id, RoomBan.song_id == song_id)).first()
        is not None
    )


def ban(session: Session, room_id: int, song_id: int) -> None:
    """Blocks song_id in room_id and drops every entry of that song from the queue."""
    with _transaction(session):
        _lock_room(session, room_id)
        session.add(RoomBan(room_id=room_id, song_id=song_id))
        entries = session.exec(
            select(QueueItem).where(QueueItem.room_id == room_id, QueueItem.song_id == song_id)
        ).all()
        for entry in entries:
            session.delete(entry)
        _renumber(session, room_id, ordered_ids(session, room_id))


def unban(session: Session, room_id: int, song_id: int) -> None:
    """Lifts the ban of song_id in room_id. Nothing happens when the song is not banned."""
    with _transaction(session):
        _lock_room(session, room_id)
        row = session.exec(select(RoomBan).where(RoomBan.room_id == room_id, RoomBan.song_id == song_id)).first()
        if row is not None:
            session.delete(row)


def current_entry(session: Session, room_id: int) -> QueueItem | None:
    """The entry that plays or pauses in room_id."""
    return session.exec(
        select(QueueItem).where(
            QueueItem.room_id == room_id,
            col(QueueItem.state).in_(("playing", "paused")),
        )
    ).first()


def score_of(session: Session, entry_id: int) -> int:
    """Net vote score of one entry, counted from its rows."""
    total = session.scalar(select(func.sum(Vote.weight)).where(Vote.queue_item_id == entry_id))
    return int(total or 0)


def _finish_current(session: Session, room_id: int) -> None:
    """Moves the entry that plays to played history and drops its position."""
    current = current_entry(session, room_id)
    if current is None:
        return
    current.state = "played"
    current.position = None
    session.add(current)


def move(session: Session, room_id: int, item_id: int, position: int) -> QueueItem:
    """Moves entry item_id to position and renumbers the rest of the order."""
    with _transaction(session):
        _lock_room(session, room_id)
        entry = entry_or_404(session, room_id, item_id)
        entry_id = required_id(entry.id, "queue entry")
        ids = ordered_ids(session, room_id)
        if entry_id not in ids:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Entry {item_id} is {entry.state}, not in the order")

        index = max(0, min(position, len(ids) - 1))
        ids.remove(entry_id)
        ids.insert(index, entry_id)
        _renumber(session, room_id, ids)
        session.flush()
        session.refresh(entry)
        return entry


def accept_entry(session: Session, room_id: int, item_id: int) -> QueueItem:
    """Temporary stand-in for the audio gate: moves a requested entry to queued at the end of the order."""
    with _transaction(session):
        _lock_room(session, room_id)
        entry = entry_or_404(session, room_id, item_id)
        if entry.state != "requested":
            raise HTTPException(status.HTTP_409_CONFLICT, f"Entry {item_id} is {entry.state}")

        entry.state = "queued"
        entry.position = None
        session.add(entry)
        _renumber(session, room_id, ordered_ids(session, room_id))
        session.flush()
        session.refresh(entry)
        return entry


def toggle_player(session: Session, room_id: int) -> QueueItem:
    """Flips the entry that plays between playing and paused, so it keeps the player slot."""
    with _transaction(session):
        _lock_room(session, room_id)
        current = current_entry(session, room_id)
        if current is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Nothing plays in this room")
        current.state = "paused" if current.state == "playing" else "playing"
        session.add(current)
        session.flush()
        session.refresh(current)
        return current


def play_next(session: Session, room_id: int, amount: int = 1) -> QueueItem:
    """Ends the track that plays and starts the entry amount places ahead in the order.
    Skipped entries stay in the order, they never played.
    """
    with _transaction(session):
        _lock_room(session, room_id)
        current = current_entry(session, room_id)
        ids = ordered_ids(session, room_id)
        # the entry that plays sits at slot 0, so the entries ahead start after it
        ahead = ids[1:] if current is not None else ids
        if amount > len(ahead):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Only {len(ahead)} entries ahead in this room")

        entry_id = ahead[amount - 1]
        if score_of(session, entry_id) <= 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Entry {entry_id} has no upvote, so it stays out of the player",
            )

        _finish_current(session, room_id)
        return _start(session, room_id, entry_id)


def _start(session: Session, room_id: int, entry_id: int) -> QueueItem:
    """Moves entry entry_id to playing at the first slot. Callers hold the room lock."""
    entry = session.get(QueueItem, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Queue entry not found")
    entry.state = "playing"
    entry.played_at = datetime.datetime.now(datetime.UTC)
    session.add(entry)
    ids = ordered_ids(session, room_id)
    if entry_id in ids:
        ids.remove(entry_id)
        ids.insert(0, entry_id)
    _renumber(session, room_id, ids)
    session.flush()
    session.refresh(entry)
    return entry


def play_prev(session: Session, room_id: int, amount: int = 1) -> QueueItem:
    """Ends the track that plays and starts the track played amount tracks before it."""
    with _transaction(session):
        _lock_room(session, room_id)
        current = current_entry(session, room_id)
        current_id = current.id if current is not None else None
        _finish_current(session, room_id)
        played = session.exec(
            select(QueueItem)
            .where(QueueItem.room_id == room_id, QueueItem.state == "played")
            .order_by(col(QueueItem.played_at).desc())
        ).all()
        history = [row for row in played if row.id != current_id]
        if amount > len(history):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Only {len(history)} tracks played before this one")

        entry = history[amount - 1]
        entry_id = required_id(entry.id, "queue entry")
        if score_of(session, entry_id) <= 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Entry {entry_id} has no upvote, so it stays out of the player",
            )

        entry.state = "queued"
        session.add(entry)
        session.flush()
        return _start(session, room_id, entry_id)


def remove_entry(session: Session, room_id: int, item_id: int) -> None:
    """Deletes entry item_id and renumbers the rest of the order."""
    with _transaction(session):
        _lock_room(session, room_id)
        entry = entry_or_404(session, room_id, item_id)
        session.delete(entry)
        _renumber(session, room_id, ordered_ids(session, room_id))


def set_vote(session: Session, room_id: int, item_id: int, user: src.models.User, weight: int) -> Vote:
    """Stores weight as the vote of user on entry item_id. Callers pass 1 or -1 only."""
    with _transaction(session):
        _lock_room(session, room_id)
        entry = entry_or_404(session, room_id, item_id)
        entry_id = required_id(entry.id, "queue entry")
        user_id = required_id(user.id, "user")
        existing = session.exec(
            select(Vote).where(Vote.queue_item_id == entry_id, Vote.user_id == user_id)
        ).first()
        if existing is None:
            existing = Vote(queue_item_id=entry_id, user_id=user_id, weight=weight)
            session.add(existing)
        else:
            existing.weight = weight
            session.add(existing)
        session.flush()
        session.refresh(existing)
        return existing


def clear_vote(session: Session, room_id: int, item_id: int, user: src.models.User) -> None:
    """Removes the vote of user on entry item_id."""
    with _transaction(session):
        _lock_room(session, room_id)
        entry = entry_or_404(session, room_id, item_id)
        existing = session.exec(
            select(Vote).where(
                Vote.queue_item_id == required_id(entry.id, "queue entry"),
                Vote.user_id == required_id(user.id, "user"),
            )
        ).first()
        if existing is not None:
            session.delete(existing)


def vote_counts(session: Session, ids: list[int]) -> dict[int, int]:
    """Net vote weight per entry, keyed by entry id."""
    if not ids:
        return {}
    rows = session.exec(
        select(Vote.queue_item_id, func.sum(Vote.weight))
        .where(col(Vote.queue_item_id).in_(ids))
        .group_by(col(Vote.queue_item_id))
    ).all()
    return {int(row[0]): int(row[1] or 0) for row in rows}


def votes_by_user(session: Session, ids: list[int], user_id: int) -> dict[int, int]:
    """Vote weight that user_id holds per entry, keyed by entry id."""
    if not ids:
        return {}
    rows = session.exec(
        select(Vote.queue_item_id, Vote.weight).where(col(Vote.queue_item_id).in_(ids), col(Vote.user_id) == user_id)
    ).all()
    return {int(row[0]): int(row[1]) for row in rows}


def order_of(session: Session, room_id: int) -> list[QueueItem]:
    """Queued and playing entries of room_id, in position order."""
    return list(
        session.exec(
            select(QueueItem)
            .where(QueueItem.room_id == room_id, col(QueueItem.state).in_(ORDERED))
            .order_by(col(QueueItem.position), col(QueueItem.id))
        ).all()
    )


def history_of(session: Session, room_id: int, limit: int = 10) -> list[QueueItem]:
    """Played entries of room_id, newest first."""
    return list(
        session.exec(
            select(QueueItem)
            .where(QueueItem.room_id == room_id, QueueItem.state == "played")
            .order_by(col(QueueItem.played_at).desc())
            .limit(limit)
        ).all()
    )
