"""Response models of the queues service."""

from common.schemas import SongPayload, Status
from pydantic import BaseModel


class EntryPayload(BaseModel):
    """A queue entry as a client sees it, with the song and the vote score."""

    id: int | None
    song_id: int
    state: str  # requested, queued, playing, paused or played
    position: int | None  # None for requested and played entries
    added_by: int | None
    added_by_name: str | None
    played_at: str | None  # ISO 8601
    score: int  # sum of the votes
    my_vote: int | None  # 1, -1, or None if the caller did not vote
    playable: bool  # False when the score is not above 0
    song: SongPayload


class EntryResponse(Status):
    """One entry and the status of the request."""

    entry: EntryPayload


class QueueView(BaseModel):
    order: list[EntryPayload]
    pending: list[EntryPayload]
    history: list[EntryPayload]
    banned: list[int]  # ids of the banned songs


class RoomPublic(BaseModel):
    id: int | None
    name: str
    user_id: int  # the host
    description: str | None
    is_password_protected: bool


class RoomCreated(Status):
    room_id: int | None


class DeleteUserResult(Status):
    rooms_deleted: int
