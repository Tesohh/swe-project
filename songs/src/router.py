from pathlib import Path
from typing import Annotated

import yt_dlp
from common.schemas import SongPayload, Status, errors
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import col, select

import src.db
from src.download import MEDIA_TYPES, SEARCH_OPTS, download_song, ensure_file, song_file, song_or_404
from src.models import Song

router = APIRouter(prefix="/song")

# routes for the other services. The gateway does not route /internal, so the browser cannot reach them
internal = APIRouter(prefix="/internal")


class SongResponse(Status):
    """A song and the status of the request."""

    song: SongPayload


class SongEnvelope(BaseModel):
    """A song, for the other services."""

    song: SongPayload


class SongList(BaseModel):
    """Songs, for the other services."""

    songs: list[SongPayload]


class SearchResult(BaseModel):
    title: str | None
    url: str | None
    thumbnail: str | None
    duration: float | None


class SearchResponse(Status):
    results: list[SearchResult]


SEARCH_LIMIT = 5  # results of one search


def song_payload(song: Song, path: Path | None) -> SongPayload:
    """The row fields a client sees, plus the file name it is saved under."""
    return SongPayload(
        id=song.id,
        title=song.title,
        artist=song.artist,
        uploader=song.uploader,
        duration=song.duration,
        source_id=song.source_id,
        source_url=song.source_url,
        found_by=song.found_by,
        genre=song.genre,
        mood=song.mood,
        quality=song.quality,
        filename=path.name if path else None,
    )


@router.post("/download", responses=errors(400, 422, 502))
async def download(url: str, session: src.db.SessionDep) -> SongResponse:
    """Stores the song in the songs table and saves the file as songs/<song id>. url is the input the song was found by."""
    song = await download_song(session, url)
    return SongResponse(song=song_payload(song, song_file(song.id)))


@router.get(
    "/stream/{song_id}",
    response_class=FileResponse,
    responses={200: {"content": {"audio/*": {}}, "description": "The audio file"}, **errors(404, 502)},
)
def stream_song(song_id: int, session: src.db.SessionDep) -> FileResponse:
    """Streams the audio file of a song by its DB id. Supports Range requests for seeking."""
    song = song_or_404(session, song_id)
    # the row exists but the file does not, so the song is downloaded again
    path = ensure_file(song)

    return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"))


@router.get("/info/{song_id}", responses=errors(404))
def song_info(song_id: int, session: src.db.SessionDep) -> SongResponse:
    """Fields of a song row, plus the file name the audio is saved under."""
    song = song_or_404(session, song_id)
    return SongResponse(song=song_payload(song, song_file(song.id)))


@router.get("/search")
def search(query: str) -> SearchResponse:
    """Searches the web for songs that match query. Returns up to 5 results, and nothing is downloaded."""
    with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
        info = ydl.extract_info(f"ytsearch{SEARCH_LIMIT}:{query}", download=False)

    results = []
    if info and "entries" in info:
        for entry in info["entries"]:
            results.append(
                SearchResult(
                    title=entry.get("title"),
                    url=entry.get("webpage_url"),
                    thumbnail=entry.get("thumbnail"),
                    duration=entry.get("duration"),
                )
            )

    return SearchResponse(results=results)


class FromUrlBody(BaseModel):
    query: str = Field(min_length=1)


@internal.post("/songs/from-url", responses=errors(400, 422, 502))
async def song_from_url(body: FromUrlBody, session: src.db.SessionDep) -> SongEnvelope:
    """Downloads the song that query names, or reuses it. Called by the queues service."""
    song = await download_song(session, body.query)
    return SongEnvelope(song=song_payload(song, song_file(song.id)))


@internal.get("/songs")
def songs_by_ids(session: src.db.SessionDep, ids: Annotated[list[int] | None, Query()] = None) -> SongList:
    """Payloads of the songs with these ids. An id that does not exist is left out."""
    if not ids:
        return SongList(songs=[])
    rows = session.exec(select(Song).where(col(Song.id).in_(ids))).all()
    return SongList(songs=[song_payload(row, song_file(row.id)) for row in rows])
