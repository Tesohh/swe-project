from pathlib import Path
from typing import Annotated

import yt_dlp
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import col, select

import src.db
from src.download import MEDIA_TYPES, SEARCH_OPTS, download_song, ensure_file, song_file, song_or_404
from src.models import Song

router = APIRouter(prefix="/song")

# routes for the other services. The gateway does not route /internal, so the browser cannot reach them
internal = APIRouter(prefix="/internal")


def song_payload(song: Song, path: Path | None) -> dict:
    """The row fields a client sees, plus the file name it is saved under."""
    return {
        "id": song.id,
        "title": song.title,
        "artist": song.artist,
        "uploader": song.uploader,
        "duration": song.duration,
        "source_id": song.source_id,
        "source_url": song.source_url,
        "found_by": song.found_by,
        "genre": song.genre,
        "mood": song.mood,
        "quality": song.quality,
        "filename": path.name if path else None,
    }


@router.get("/download")
def download(url: str, session: src.db.SessionDep):
    """Stores the song in the songs table and saves the file as songs/<song id>. url is the input the song was found by."""
    song = download_song(session, url)
    path = song_file(song.id)

    return JSONResponse({"status": "ok", "song": song_payload(song, path)})


@router.get("/stream/{song_id}")
def stream_song(song_id: int, session: src.db.SessionDep):
    """Streams the audio file of a song by its DB id. Supports Range requests for seeking."""
    song = song_or_404(session, song_id)
    # the row exists but the file does not, so the song is downloaded again
    path = ensure_file(song)

    return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"))


@router.get("/info/{song_id}")
def song_info(song_id: int, session: src.db.SessionDep):
    """Fields of a song row, plus the file name the audio is saved under."""
    song = song_or_404(session, song_id)
    return JSONResponse({"status": "ok", "song": song_payload(song, song_file(song.id))})


@router.get("/search")
def search(query: str):
    with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
        info = ydl.extract_info(f"ytsearch{5}:{query}", download=False)

    results = []
    if info and "entries" in info:
        for entry in info["entries"]:
            results.append(
                {
                    "title": entry.get("title"),
                    "url": entry.get("webpage_url"),
                    "thumbnail": entry.get("thumbnail"),
                    "duration": entry.get("duration"),
                }
            )

    return JSONResponse({"status": "ok", "results": results})


class FromUrlBody(BaseModel):
    query: str = Field(min_length=1)


@internal.post("/songs/from-url")
def song_from_url(body: FromUrlBody, session: src.db.SessionDep):
    """Downloads the song that query names, or reuses it. Called by the queues service."""
    song = download_song(session, body.query)
    return JSONResponse({"song": song_payload(song, song_file(song.id))})


@internal.get("/songs")
def songs_by_ids(session: src.db.SessionDep, ids: Annotated[list[int] | None, Query()] = None):
    """Payloads of the songs with these ids. An id that does not exist is left out."""
    if not ids:
        return JSONResponse({"songs": []})
    rows = session.exec(select(Song).where(col(Song.id).in_(ids))).all()
    return JSONResponse({"songs": [song_payload(row, song_file(row.id)) for row in rows]})
