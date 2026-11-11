"""Download songs with yt-dlp and store each one as a row in the songs table.

The DB row id is the filename on disk: songs/<id>.mp3.
"""

from pathlib import Path

import yt_dlp
from fastapi import HTTPException, status
from sqlmodel import select

import src.db
from src.models import Song

SONGS_DIR = Path("./songs")
PARTIAL_SUFFIXES = (".part", ".partial", ".frag", ".ytdl")

# media type for the audio file yt-dlp wrote, keyed by extension
MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".opus": "audio/opus",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}

DOWNLOAD_OPTS = {
    "format": "bestaudio/best",
    "merge_output_format": "mp3",
    "quiet": True,
    "no_warnings": True,
    "js_runtimes": {"node": {"path": "/usr/bin/node"}},
}


def song_file(song_id: int | None) -> Path | None:
    """Path of the file yt-dlp wrote for a song, or None if it is missing."""
    if song_id is None:
        return None
    for path in sorted(SONGS_DIR.glob(f"{song_id}.*")):
        if path.is_file() and not path.name.endswith(PARTIAL_SUFFIXES):
            return path
    return None


def _extract_info(url: str) -> dict:
    try:
        with yt_dlp.YoutubeDL(DOWNLOAD_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Cannot read song from {url}: {err}") from err

    if not info or not info.get("title"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Cannot read song from {url}: no title found")
    return info


def download_song(session: src.db.SessionDep, url: str, found_by: str | None = None) -> Song:
    """Downloads url into songs/<song id> and returns the row that stores it. Reuses the row if the song was already downloaded."""
    SONGS_DIR.mkdir(parents=True, exist_ok=True)

    existing = session.exec(select(Song).where(Song.source_url == url)).first()
    if existing is not None:
        if song_file(existing.id) is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Song {existing.id} has no file on disk")
        return existing

    info = _extract_info(url)

    song = Song(
        title=info["title"],
        artist=info.get("artist") or info.get("uploader"),
        uploader=info.get("uploader"),
        duration=info.get("duration"),
        source_id=info.get("id"),
        found_by=found_by or url,
        source_url=url,
    )
    session.add(song)
    session.commit()
    session.refresh(song)

    opts = {**DOWNLOAD_OPTS, "outtmpl": str(SONGS_DIR / f"{song.id}.%(ext)s")}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as err:
        session.rollback()
        session.delete(song)
        session.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Download failed: {err}") from err

    if song_file(song.id) is None:
        session.delete(song)
        session.commit()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Download produced no file")

    return song
