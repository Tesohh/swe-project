"""Download songs with yt-dlp and store each one as a row in the songs table.

The DB row id is the filename on disk: songs/<id>.mp3.
"""

import threading
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

# one lock per song id so concurrent requests cannot write songs/<id> at the same time
_download_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()

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


def song_or_404(session: src.db.SessionDep, song_id: int) -> Song:
    """Song row for song_id, or 404 if it is not in the songs table."""
    song = session.get(Song, song_id)
    if song is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No song with id {song_id}")
    return song


class _DownloadFailed(Exception):
    """yt-dlp did not write the file for a song."""


def _song_lock(song_id: int) -> threading.Lock:
    with _locks_guard:
        return _download_locks.setdefault(song_id, threading.Lock())


def _remove_partials(song_id: int) -> None:
    """Deletes leftover partial downloads so a retry does not resume a broken file."""
    for path in SONGS_DIR.glob(f"{song_id}.*"):
        if path.is_file() and path.name.endswith(PARTIAL_SUFFIXES):
            path.unlink(missing_ok=True)


def _download_to(url: str, song_id: int | None) -> Path:
    """Writes the audio of url to songs/<song_id> and returns the file it wrote."""
    if song_id is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Song has no id")

    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    opts = {**DOWNLOAD_OPTS, "outtmpl": str(SONGS_DIR / f"{song_id}.%(ext)s")}

    with _song_lock(song_id):
        # another request may have written the file while this one waited for the lock
        path = song_file(song_id)
        if path is not None:
            return path

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError as err:
            _remove_partials(song_id)
            raise _DownloadFailed(str(err)) from err

        path = song_file(song_id)
        if path is None:
            _remove_partials(song_id)
            raise _DownloadFailed("Download produced no file")
        return path


def ensure_file(song: Song) -> Path:
    """Audio file of a song, re-downloaded from source_url when it is missing on disk."""
    path = song_file(song.id)
    if path is not None:
        return path

    if song.source_url is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Song {song.id} has no source url to re-download")

    try:
        return _download_to(song.source_url, song.id)
    except _DownloadFailed as err:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Re-download of song {song.id} failed: {err}") from err


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
        ensure_file(existing)
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

    try:
        _download_to(url, song.id)
    except _DownloadFailed as err:
        session.delete(song)
        session.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Download failed: {err}") from err

    return song
