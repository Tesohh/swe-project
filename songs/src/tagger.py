"""Tags a downloaded song with the tagger (inference) service.

The tagger is slow and may be down. A failure never blocks a download: the song stays untagged.
"""

import logging
from pathlib import Path

import httpx
from common.http import base_url
from sqlmodel import Session

from src.models import Song

log = logging.getLogger(__name__)

TAGGER_TIMEOUT_SECONDS = 120.0
MIN_P_MUSIC = 0.5  # below this the audio is not music


def tag_song(session: Session, song: Song, path: Path, media_type: str) -> None:
    """Stores genre, mood and quality of song, as the tagger reports them for its audio file at path."""
    url = f"{base_url('INFERENCE_TAGGER_BASE', 'http://inference:8000')}/analyze"
    try:
        with path.open("rb") as audio:
            response = httpx.post(
                url,
                files={"file": (path.name, audio, media_type)},
                params={"top_k": 1},
                timeout=TAGGER_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as err:
        log.warning("could not tag song %s: %s", song.id, err)
        return

    song.genre = next(iter(result["genre"]), None)
    song.mood = next(iter(result["mood"]), None)
    song.quality = "good" if result["p_music"] >= MIN_P_MUSIC else "not_music"
    session.add(song)
    session.commit()
    session.refresh(song)
