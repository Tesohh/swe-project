"""YouTube negatives stage: real non-music audio (ambience, sound effects, speech).

Searches YouTube for non-music topics, downloads one 60 s section per video into the raw
audio dir under a stable id, and writes a manifest. The artist field holds the uploader,
so artist-grouped validation holds out whole channels. Videos and uploaders listed in
data/neg_test_exclude.txt (the held-out test clips) are never downloaded.
Music inside a clip is removed later, per window, by ml.dataset.filter_music.
"""

import argparse
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import HttpUrl

from ml.dataset.collect import DATA_DIR, MANIFEST_DIR, _write_manifest
from ml.dataset.manifest import ManifestRow, load_manifest, stable_id
from ml.dataset.vocabs import AudioType, LabelOrigin, Source

EXCLUDE_PATH = DATA_DIR / "neg_test_exclude.txt"
SECTION = (30, 90)
MAX_PER_UPLOADER = 6

PLACES = [
    "cafe", "restaurant dinner", "bar", "pub", "food court", "train station", "airport terminal",
    "shopping mall", "school cafeteria", "gym", "farmers market", "city bus", "subway train",
    "beach boardwalk", "city park", "playground", "football stadium", "library", "open office",
    "hospital waiting room", "street festival", "night market", "swimming pool", "bus station",
]  # fmt: skip
NATURE = [
    "rain on window", "thunderstorm", "ocean waves shore", "river stream", "forest birds morning",
    "wind in trees", "campfire crackling", "jungle night insects", "waterfall", "blizzard wind",
    "heavy rain on tent", "crickets summer night",
]  # fmt: skip
SFX = [
    "vacuum cleaner", "washing machine", "helicopter flyby", "lawn mower", "chainsaw",
    "car engine idle", "train passing by", "airplane takeoff", "construction site",
    "kitchen cooking", "keyboard typing", "clock ticking", "fireworks", "ambulance siren",
    "door slam", "glass breaking", "footsteps gravel", "fan noise", "air conditioner hum",
    "dishwasher",
]  # fmt: skip
CROWD = [
    "audience applause", "crowd cheering", "football fans chanting", "protest crowd",
    "children playing", "wedding guests chatter",
]  # fmt: skip
TALK = [
    "interview", "news report", "university lecture", "sermon", "sports commentary",
    "radio call in", "documentary narration", "ted talk", "audiobook reading",
    "cooking tutorial", "gaming commentary", "tech review", "weather forecast",
    "parliament debate", "history lecture", "comedy podcast", "science podcast",
    "true crime podcast", "business podcast", "storytelling",
]  # fmt: skip
LANGUAGES = [
    "noticias en espanol", "noticias em portugues", "actualites en francais",
    "nachrichten auf deutsch", "notizie italiano telegiornale", "japanese news broadcast",
    "korean news broadcast", "arabic news broadcast", "hindi news broadcast",
    "russian news broadcast", "turkish news broadcast", "polish news broadcast",
    "podcast en espanol", "podcast italiano", "podcast en francais", "podcast auf deutsch",
    "audiolibro italiano", "audiolibro espanol", "conferenza italiano", "entrevista en espanol",
]  # fmt: skip

SEARCH_SUFFIX = {"ambience": "ambience no music", "nature": "sounds no music", "sfx": "sound",
                 "crowd": "sound", "talk": "", "foreign": ""}  # fmt: skip
GROUPS = {
    "ambience": (PLACES, AudioType.NOISE, Source.NOISE),
    "nature": (NATURE, AudioType.NOISE, Source.NOISE),
    "sfx": (SFX, AudioType.NOISE, Source.NOISE),
    "crowd": (CROWD, AudioType.NOISE, Source.NOISE),
    "talk": (TALK, AudioType.SPEECH, Source.SPEECH),
    "foreign": (LANGUAGES, AudioType.SPEECH, Source.SPEECH),
}
PER_QUERY = {"ambience": 6, "nature": 6, "sfx": 6, "crowd": 6, "talk": 5, "foreign": 5}


def load_exclude(path: Path = EXCLUDE_PATH) -> tuple[set[str], set[str]]:
    """Video ids and uploader names that must not enter training."""
    ids, uploaders = set(), set()
    for line in path.read_text().splitlines():
        kind, _, value = line.partition(" ")
        (ids if kind == "id" else uploaders).add(value)
    return ids, uploaders


def jobs() -> list[tuple[str, str, int]]:
    out = []
    for group, (topics, _, _) in GROUPS.items():
        for topic in topics:
            out.append((group, f"{topic} {SEARCH_SUFFIX[group]}".strip(), PER_QUERY[group]))
    return out


def fetch_query(
    job: tuple[str, str, int], raw_dir: Path, exclude: tuple[set[str], set[str]]
) -> list[ManifestRow]:
    """Download the first usable results of one search; returns their manifest rows."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    group, query, count = job
    _, audio_type, source = GROUPS[group]
    bad_ids, bad_uploaders = exclude

    def reject(info, incomplete=False):
        if info.get("_type") == "playlist":  # the search result itself, not a video
            return None
        if info.get("id") in bad_ids or info.get("uploader") in bad_uploaders:
            return "held-out test video or uploader"
        if info.get("duration") is not None and info["duration"] < 90:
            return "shorter than 90 s"
        return None

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(raw_dir / "ytneg_%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "download_ranges": download_range_func(None, [SECTION]),
        "match_filter": reject,
        "ignoreerrors": True,
    }
    rows = []
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"ytsearch{count}:{query}", download=True) or {}
    except Exception:  # noqa: BLE001 - one failed search must not stop the run
        return rows
    for entry in info.get("entries") or []:
        if not entry:
            continue
        downloaded = list(raw_dir.glob(f"ytneg_{entry['id']}.*"))
        if not downloaded:
            continue
        row_id = stable_id("ytneg", entry["id"])
        final = raw_dir / f"{row_id}{downloaded[0].suffix}"
        try:
            if final.exists():
                downloaded[0].unlink()
            else:
                downloaded[0].rename(final)
        except FileNotFoundError:  # another worker handled the same video
            pass
        rows.append(
            ManifestRow(
                id=row_id,
                url=HttpUrl(f"https://www.youtube.com/watch?v={entry['id']}"),
                title=(entry.get("title") or entry["id"])[:120],
                artist=entry.get("uploader") or f"unknown {entry['id']}",
                source=source,
                audio_type=audio_type,
                label_origin=LabelOrigin.MANUAL,
                notes=f"ytneg group: {group}, query: {query}, video: {entry['id']}",
            )
        )
    return rows


def cap_per_uploader(rows: list[ManifestRow], cap: int = MAX_PER_UPLOADER) -> list[ManifestRow]:
    """Keep at most `cap` clips per uploader so no channel dominates."""
    seen: Counter[str] = Counter()
    kept = []
    for row in rows:
        seen[row.artist] += 1
        if seen[row.artist] <= cap:
            kept.append(row)
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download real non-music negatives from YouTube")
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--out", type=Path, default=MANIFEST_DIR / "ytneg.csv")
    parser.add_argument("--workers", type=int, default=6, help="parallel searches")
    args = parser.parse_args(argv)

    exclude = load_exclude()
    # resume: rows from an earlier run stay, and their videos are not fetched again
    rows: dict[str, ManifestRow] = {}
    if args.out.exists():
        rows = {row.id: row for row in load_manifest(args.out).rows}
    all_jobs = jobs()
    lock = threading.Lock()
    done = 0

    def work(job):
        nonlocal done
        found = fetch_query(job, args.raw_dir, exclude)
        with lock:
            for row in found:
                rows[row.id] = row
            done += 1
            print(f"{done}/{len(all_jobs)} {job[0]}: {job[1]} -> {len(found)} clips, {len(rows)} total", flush=True)
            _write_manifest(args.out, cap_per_uploader(list(rows.values())))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, all_jobs))
    kept = cap_per_uploader(list(rows.values()))
    _write_manifest(args.out, kept)
    print(f"wrote {len(kept)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
