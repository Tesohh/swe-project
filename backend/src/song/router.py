from pathlib import Path

import yt_dlp
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

import src.db
from src.models import Song
from src.song.download import MEDIA_TYPES, SEARCH_OPTS, download_song, ensure_file, song_file, song_or_404

router = APIRouter(prefix="/song")


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
