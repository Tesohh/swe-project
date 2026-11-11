"""Entry payloads shared by the user router and the host router."""

from fastapi import HTTPException, status
from sqlmodel import Session, col, select

import src.models
from src.models import QueueItem, Song
from src.queue.order import entry_or_404, required_id, vote_counts, votes_by_user
from src.song.download import song_file
from src.song.router import song_payload


def entry_payload(entry: QueueItem, song: Song, score: int, my_vote: int | None) -> dict:
    """The entry fields a client sees, plus the song and the vote score."""
    return {
        "id": entry.id,
        "song_id": song.id,
        "state": entry.state,
        "position": entry.position,
        "added_by": entry.added_by,
        "played_at": entry.played_at.isoformat() if entry.played_at else None,
        "score": score,
        "my_vote": my_vote,
        "playable": score > 0,  # a track with no upvote stays out of the player
        "song": song_payload(song, song_file(song.id)),
    }


def build_entries(session: Session, entries: list[QueueItem], user: src.models.User | None) -> list[dict]:
    """Payload list for entries, with the vote score of each entry."""
    ids = [required_id(entry.id, "queue entry") for entry in entries]
    counts = vote_counts(session, ids)
    mine = votes_by_user(session, ids, required_id(user.id, "user")) if user else {}

    payloads = []
    for entry in entries:
        song = session.get(Song, entry.song_id)
        if song is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Song {entry.song_id} is missing")
        entry_id = required_id(entry.id, "queue entry")
        payloads.append(entry_payload(entry, song, counts.get(entry_id, 0), mine.get(entry_id)))
    return payloads


def pending_of(session: Session, room_id: int) -> list[QueueItem]:
    """Requested entries of room_id that wait for the audio model, oldest first."""
    return list(
        session.exec(
            select(QueueItem)
            .where(QueueItem.room_id == room_id, QueueItem.state == "requested")
            .order_by(col(QueueItem.id))
        ).all()
    )


def single_payload(session: Session, room_id: int, item_id: int, user: src.models.User) -> dict:
    """Payload of one entry, with the vote of user."""
    entry = entry_or_404(session, room_id, item_id)
    entry_id = required_id(entry.id, "queue entry")
    song = session.get(Song, entry.song_id)
    if song is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Song {entry.song_id} is missing")
    counts = vote_counts(session, [entry_id])
    mine = votes_by_user(session, [entry_id], required_id(user.id, "user"))
    return entry_payload(entry, song, counts.get(entry_id, 0), mine.get(entry_id))
