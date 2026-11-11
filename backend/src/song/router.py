import yt_dlp
from fastapi import APIRouter
from fastapi.responses import JSONResponse

import src.db
from src.song.download import download_song, song_file

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
