"""Fixed label vocabularies shared by every dataset stage."""

import json
from enum import StrEnum
from functools import cache
from pathlib import Path

# vocabs.py lives at ml/src/ml/dataset, so ml root is three parents up
DATA_DIR = Path(__file__).resolve().parents[3] / "data"

GENRE_VOCAB_PATH = DATA_DIR / "genre_vocab.json"
MOOD_VOCAB_PATH = DATA_DIR / "mood_vocab.json"


class Source(StrEnum):
    """Where the manifest row came from."""

    MTG_JAMENDO = "mtg_jamendo"
    FMA = "fma"
    FREE_MUSIC_ARCHIVE = "free_music_archive"
    YOUTUBE = "youtube"
    ARCHIVE_ORG = "archive_org"
    SPEECH = "speech"
    NOISE = "noise"
    SYNTHETIC = "synthetic"


class AudioType(StrEnum):
    """What kind of audio the clip is."

    Non-music types do not need genre or mood tags.
    """

    MUSIC = "music"
    SPEECH = "speech"
    NOISE = "noise"
    BAD_UPLOAD = "bad_upload"


class LabelOrigin(StrEnum):
    DATASET_TAG = "dataset_tag"
    AGENT = "agent"
    MEASURED = "measured"
    MANUAL = "manual"


@cache
def load_genres() -> frozenset[str]:
    return frozenset(_load_vocab(GENRE_VOCAB_PATH, "genres"))


@cache
def load_moods() -> frozenset[str]:
    return frozenset(_load_vocab(MOOD_VOCAB_PATH, "moods"))


def _load_vocab(path: Path, key: str) -> frozenset[str]:
    data = json.loads(path.read_text())
    return frozenset(data[key])
