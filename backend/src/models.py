import datetime

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

# queue states that queue_items.state may hold
QUEUE_STATES = ("requested", "queued", "playing", "paused", "played")
# states that hold a position in the room order
ORDERED_STATES = ("queued", "playing")
STATE_IN = "(" + ", ".join(f"'{state}'" for state in QUEUE_STATES) + ")"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    password_hash: str


class Room(SQLModel, table=True):
    __tablename__ = "rooms"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    user_id: int = Field(foreign_key="users.id")  # host user who created the room
    password_hash: str | None  # if set, the room is "password protected"

    description: str | None  # plain text sent to the Decision model to filter song requests


class Song(SQLModel, table=True):
    __tablename__ = "songs"

    id: int | None = Field(default=None, primary_key=True)

    title: str
    artist: str | None

    found_by: str = Field(nullable=False)  # how was this song found? eg. "despacito" or "https://www.youtube.com/watch?v=6UU5Fzz661k"

    source_url: str | None = Field(default=None, index=True, unique=True)  # url yt-dlp downloaded the song from
    source_id: str | None = None  # yt-dlp video id (eg. "6UU5Fzz661k")
    uploader: str | None = None  # channel/artist name reported by yt-dlp
    duration: int | None = None  # seconds of the audio

    # reported by the audio model
    genre: str | None = None  # eg. "rap", "rock", "metal"
    mood: str | None = None  # eg. "calm", "sad"
    quality: str | None = None  # eg. "good", "troll", "podcast" (anything that isn't "good" is rejected)


class QueueItem(SQLModel, table=True):
    """One song request in one room. The order lives in position, dense integers from 0."""

    __tablename__ = "queue_items"
    __table_args__ = (
        UniqueConstraint("room_id", "song_id", name="uq_room_song"),  # one entry per song per room
        UniqueConstraint("room_id", "position", name="uq_room_position"),  # no two entries share a position
        Index(
            "uq_room_playing",
            "room_id",
            postgresql_where=text("state IN ('playing', 'paused')"),
            unique=True,  # at most one entry plays or pauses per room
        ),
        Index("ix_queue_room_order", "room_id", "state", "position"),
        CheckConstraint(f"state IN {STATE_IN}", name="ck_queue_state"),
    )

    id: int | None = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="rooms.id", index=True, ondelete="CASCADE")
    song_id: int = Field(foreign_key="songs.id", index=True, ondelete="RESTRICT")

    state: str = Field(default="queued", index=True)
    position: int | None = None  # None for requested and played entries

    added_by: int | None = Field(foreign_key="users.id", ondelete="SET NULL")
    played_at: datetime.datetime | None = None


class Vote(SQLModel, table=True):
    """One vote per user per queue entry."""

    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("queue_item_id", "user_id", name="uq_vote_once"),
        CheckConstraint("weight IN (-1, 1)", name="ck_vote_weight"),  # a score of ±1, never higher
    )

    id: int | None = Field(default=None, primary_key=True)
    queue_item_id: int = Field(foreign_key="queue_items.id", index=True, ondelete="CASCADE")
    user_id: int = Field(foreign_key="users.id", index=True, ondelete="CASCADE")
    weight: int = Field(default=1)  # 1 or -1, so a user can downvote


class RoomBan(SQLModel, table=True):
    """A song the host banned in one room. A banned song never enters that queue again."""

    __tablename__ = "room_bans"
    __table_args__ = (UniqueConstraint("room_id", "song_id", name="uq_room_ban"),)

    id: int | None = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="rooms.id", index=True, ondelete="CASCADE")
    song_id: int = Field(foreign_key="songs.id", index=True, ondelete="CASCADE")
