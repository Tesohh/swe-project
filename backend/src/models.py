from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    password_hash: str


class Room(SQLModel, table=True):
    __tablename__ = "rooms"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    password_hash: str | None  # if set, the room is "password protected"

    description: str | None  # plain text sent to the Decision model to filter song requests


class Song(SQLModel, table=True):
    __tablename__ = "songs"

    id: int | None = Field(default=None, primary_key=True)

    title: str
    artist: str | None

    found_by: str  # how was this song found? eg. "despacito" or "https://www.youtube.com/watch?v=6UU5Fzz661k"

    # reported by the audio model
    genre: str | None  # eg. "rap", "rock", "metal"
    mood: str | None  # eg. "calm", "sad"
    quality: str | None  # eg. "good", "troll", "podcast" (anything that isn't "good" is rejected)
