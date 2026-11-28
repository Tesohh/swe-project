"""Tags a downloaded song with the tagger (inference) service.

The tagger is slow and may be down. A failure never blocks a download: the song stays untagged.
"""

import asyncio
import logging
from pathlib import Path

import httpx
from common.http import base_url
from sqlmodel import Session

from src.models import Song

log = logging.getLogger(__name__)

TAGGER_TIMEOUT_SECONDS = 120.0
MIN_P_MUSIC = 0.5  # below this the audio is not music


async def tag_song(session: Session, song: Song, path: Path, media_type: str) -> None:
    """Stores genre, mood and quality of song, as the tagger reports them for its audio file at path."""
    url = f"{base_url('INFERENCE_TAGGER_BASE', 'http://inference:8000')}/analyze"
    try:
        audio = await asyncio.to_thread(path.read_bytes)
        async with httpx.AsyncClient(timeout=TAGGER_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                files={"file": (path.name, audio, media_type)},
                params={"top_k": 1},
            )
        response.raise_for_status()
        result = response.json()
        genre = next(iter(result["genre"]), None)
        mood = next(iter(result["mood"]), None)
        quality = "good" if result["p_music"] >= MIN_P_MUSIC else "not_music"
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
        log.warning("could not tag song %s: %s", song.id, err)
        return

    song.genre = genre
    song.mood = mood
    song.quality = quality
    session.add(song)
    session.commit()
    session.refresh(song)
