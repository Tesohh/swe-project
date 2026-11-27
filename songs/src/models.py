from sqlmodel import Field, SQLModel


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

    # reported by the tagger service
    genre: str | None = None  # eg. "rap", "rock", "metal"
    mood: str | None = None  # eg. "calm", "sad"
    quality: str | None = None  # eg. "good", "not_music" (anything that isn't "good" is rejected)
