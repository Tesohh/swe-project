import yt_dlp
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

import src.db
from src.models import Song
from src.song.download import MEDIA_TYPES, download_song, song_file

router = APIRouter(prefix="/song")


search_opts = {
    "quiet": True,
    "no_warnings": True,
    "js_runtimes": {"node": {"path": "/usr/bin/node"}},
}


@router.get("/download")
def download(url: str, session: src.db.SessionDep):
    """Stores the song in the songs table and saves the file as songs/<song id>."""
    song = download_song(session, url)
    path = song_file(song.id)

    return JSONResponse(
        {
            "status": "ok",
            "song": {
                "id": song.id,
                "title": song.title,
                "artist": song.artist,
                "uploader": song.uploader,
                "duration": song.duration,
                "source_id": song.source_id,
                "source_url": song.source_url,
                "filename": path.name if path else None,
            },
        }
    )


@router.get("/stream/{song_id}")
def stream_song(song_id: int, session: src.db.SessionDep):
    """Streams the audio file of a song by its DB id. Supports Range requests for seeking."""
    song = session.get(Song, song_id)
    if song is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No song with id {song_id}")

    path = song_file(song.id)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Song {song_id} has no file on disk")

    return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"))


@router.get("/search")
def search(query: str):
    with yt_dlp.YoutubeDL(search_opts) as ydl:
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
