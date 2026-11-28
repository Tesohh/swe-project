"""Entry payloads shared by the user router and the host router."""

from common.auth import CurrentUser
from common.schemas import SongPayload
from sqlmodel import Session, col, select

from src.models import QueueItem
from src.queue.order import entry_or_404, required_id, vote_counts, votes_by_user
from src.schemas import EntryPayload
from src.songs import songs_by_id
from src.users import names_by_id


def entry_payload(entry: QueueItem, song: dict, score: int, my_vote: int | None, added_by_name: str | None) -> EntryPayload:
    """The entry fields a client sees, plus the song and the vote score."""
    return EntryPayload(
        id=entry.id,
        song_id=entry.song_id,
        state=entry.state,
        position=entry.position,
        added_by=entry.added_by,
        added_by_name=added_by_name,
        played_at=entry.played_at.isoformat() if entry.played_at else None,
        score=score,
        my_vote=my_vote,
        playable=score > 0,  # a track with no upvote stays out of the player
        song=SongPayload.model_validate(song),
    )


async def build_entries(session: Session, entries: list[QueueItem], user: CurrentUser | None) -> list[EntryPayload]:
    """Payload list for entries, with the vote score of each entry."""
    ids = [required_id(entry.id, "queue entry") for entry in entries]
    counts = vote_counts(session, ids)
    mine = votes_by_user(session, ids, user.id) if user else {}
    songs = await songs_by_id([entry.song_id for entry in entries])
    names = await names_by_id([entry.added_by for entry in entries if entry.added_by is not None])

    return [
        entry_payload(
            entry,
            songs[entry.song_id],
            counts.get(required_id(entry.id, "queue entry"), 0),
            mine.get(required_id(entry.id, "queue entry")),
            names.get(entry.added_by) if entry.added_by is not None else None,
        )
        for entry in entries
    ]


def pending_of(session: Session, room_id: int) -> list[QueueItem]:
    """Requested entries of room_id that wait for the audio model, oldest first."""
    return list(session.exec(select(QueueItem).where(QueueItem.room_id == room_id, QueueItem.state == "requested").order_by(col(QueueItem.id))).all())


async def single_payload(session: Session, room_id: int, item_id: int, user: CurrentUser) -> EntryPayload:
    """Payload of one entry, with the vote of user."""
    entry = entry_or_404(session, room_id, item_id)
    return (await build_entries(session, [entry], user))[0]
