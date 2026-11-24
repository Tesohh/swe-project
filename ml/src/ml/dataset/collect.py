"""Collect stage: turn public dataset metadata into manifest CSVs.

For now: MTG-Jamendo. The metadata TSVs are cached in ml/data/jamendo,
the output manifest goes to ml/data/manifests.
"""

import argparse
import csv
import json
import sys
import time
import typing
import urllib.request
from collections import Counter
from pathlib import Path

from pydantic import HttpUrl

from ml.dataset.manifest import TAG_SEPARATOR, ManifestRow, load_manifest, stable_id
from ml.dataset.progress import eta_string
from ml.dataset.vocabs import AudioType, LabelOrigin, Source, load_genres, load_moods

RAW_BASE = "https://raw.githubusercontent.com/MTG/mtg-jamendo-dataset/master/data"
# Direct per-track mp3 endpoint, verified reachable
AUDIO_URL_TEMPLATE = "https://mp3d.jamendo.com/?trackid={track_id}&format=mp31"

ARCHIVE_SEARCH_URL = (
    "https://archive.org/advancedsearch.php"
    "?q=collection%3Alibrivoxaudio+AND+mediatype%3Aaudio"
    "&fl%5B%5D=identifier&fl%5B%5D=title&rows={rows}&page={page}&output=json"
)
ARCHIVE_METADATA_URL = "https://archive.org/metadata/{item_id}"
ARCHIVE_DOWNLOAD_URL = "https://archive.org/download/{item_id}/{file_name}"

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CACHE_DIR = DATA_DIR / "jamendo"
MANIFEST_DIR = DATA_DIR / "manifests"
TAG_MAP_PATH = DATA_DIR / "jamendo_tag_map.json"

DEFAULTS = {"duration_min": 60.0, "duration_max": 600.0, "per_genre": 800}


def collect_jamendo(
    out_path: Path,
    per_genre: int = 200,
    duration_min: float = 60.0,
    duration_max: float = 600.0,
) -> None:
    """Build a balanced manifest from the MTG-Jamendo tags."""
    tag_map = _load_tag_map(TAG_MAP_PATH)
    meta = _load_meta(CACHE_DIR / "jamendo_meta.tsv")
    tags_by_track = _load_tags(CACHE_DIR / "jamendo_autotagging.tsv")
    # the mood/theme subset adds mood tags for tracks that the base file lacks
    _merge_tags(tags_by_track, _load_tags(CACHE_DIR / "jamendo_moodtheme.tsv"))

    rows = []
    for track_id, track in tags_by_track.items():
        if track_id not in meta:
            continue
        # tsv ids look like track_0000946, the mp3 endpoint wants the number
        numeric_id = int(track_id.removeprefix("track_"))
        genre, mood = _map_tags(track.tags, tag_map)
        if not genre:
            continue
        info = meta[track_id]
        if not duration_min <= track.duration <= duration_max:
            continue
        rows.append(
            ManifestRow(
                id=stable_id("jamendo", str(numeric_id)),
                url=HttpUrl(AUDIO_URL_TEMPLATE.format(track_id=numeric_id)),
                title=info["title"],
                artist=info["artist"],
                source=Source.MTG_JAMENDO,
                genre=genre,
                mood=mood,
                audio_type=AudioType.MUSIC,
                label_origin=LabelOrigin.DATASET_TAG,
                notes=f"jamendo tags: {TAG_SEPARATOR.join(sorted(track.tags))}",
            )
        )

    selected = _balance_by_genre(rows, per_genre)
    selected = _drop_title_duplicates(selected)
    _write_manifest(out_path, selected)
    genre_stats = Counter(tag for row in selected for tag in row.genre)
    mood_stats = Counter(tag for row in selected for tag in row.mood)
    mooded = sum(1 for row in selected if row.mood)
    print(f"wrote {len(selected)} rows to {out_path}")
    print("genre counts:", ", ".join(f"{tag}: {count}" for tag, count in genre_stats.most_common()))
    print(
        f"mood counts: rows with mood: {mooded}, ",
        ", ".join(f"{tag}: {count}" for tag, count in mood_stats.most_common()),
    )


def collect_librivox(
    out_path: Path,
    cap: int = 500,
    items: int = 250,
    files_per_item: int = 3,
    page: int = 1,
    duration_min: float = 60.0,
    duration_max: float = 1800.0,
) -> None:
    """Build a speech manifest from LibriVox audiobooks on archive.org."""
    # resume support: skip items that are already in the output manifest
    done_items: set[str] = set()
    existing: list[ManifestRow] = []
    if out_path.exists():
        existing = load_manifest(out_path).rows
        for row in existing:
            if "librivox item:" in row.notes:
                done_items.add(row.notes.split("librivox item: ")[1].split(",")[0])
        cap -= len(existing)
        if cap <= 0:
            print(f"{out_path} already holds {len(existing)} rows, nothing to do")
            return

    rows: list[ManifestRow] = list(existing)
    start = time.monotonic()
    scanned = 0
    for item in _archive_items(rows=items, page=page):
        if item["identifier"] in done_items:
            continue
        if len(rows) >= cap:
            break
        scanned += 1
        item_meta = _http_get_json(ARCHIVE_METADATA_URL.format(item_id=item["identifier"]))
        files = _speech_files(item_meta, duration_min, duration_max)[:files_per_item]
        for mp3 in files:
            rows.append(
                ManifestRow(
                    id=stable_id("librivox", item["identifier"], mp3["name"]),
                    url=HttpUrl(
                        ARCHIVE_DOWNLOAD_URL.format(
                            item_id=item["identifier"], file_name=mp3["name"]
                        )
                    ),
                    title=item.get("title") or mp3["name"],
                    artist=item_meta.get("metadata", {}).get("creator", ""),
                    source=Source.SPEECH,
                    audio_type=AudioType.SPEECH,
                    label_origin=LabelOrigin.DATASET_TAG,
                    notes=f"librivox item: {item['identifier']}, file: {mp3['name']}",
                )
            )
            if len(rows) >= cap:
                break
        if scanned % 10 == 0:
            print(
                f"scanned {scanned} items, {len(rows)}/{cap} rows, eta ~{eta_string(start, len(rows), cap)}",
                flush=True,
            )
    _write_manifest(out_path, rows)
    print(f"wrote {len(rows)} speech rows to {out_path}")


def _archive_items(rows: int, page: int):
    data = _http_get_json(ARCHIVE_SEARCH_URL.format(rows=rows, page=page))
    return data["response"]["docs"]


def _speech_files(item_meta: dict, duration_min: float, duration_max: float) -> list[dict]:
    """Pick the usable mp3 files of one item, sorted by name for stable chapter order."""
    files = []
    for entry in item_meta.get("files", []):
        if "mp3" not in entry.get("format", "").lower():
            continue
        if "64kb" in entry.get("name", "").lower():
            continue  # skip the low bitrate duplicates
        duration = _parse_length(entry.get("length", ""))
        if duration is None or not duration_min <= duration <= duration_max:
            continue
        files.append(entry)
    return sorted(files, key=lambda entry: entry["name"])


def _parse_length(text: str) -> float | None:
    """archive.org lengths come as '934.76' or '1:04:02'."""
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        parts = [float(part) for part in text.split(":")]
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + part
        return seconds


def _http_get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "swe-project-collect/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _load_tag_map(path: Path) -> dict[str, dict[str, list[str] | None]]:
    return json.loads(path.read_text())


def _load_meta(path: Path) -> dict[str, dict[str, str]]:
    """track id -> title, artist from raw.meta.tsv."""
    meta: dict[str, dict[str, str]] = {}
    with path.open() as file:
        next(file)  # skip tsv header
        for parts in _tsv_rows(file):
            # raw.meta.tsv columns: track_id, artist_id, album_id, title, artist, album, release, url
            meta[parts[0]] = {"title": parts[3], "artist": parts[4]}
    return meta


class TrackTags(typing.NamedTuple):
    duration: float
    tags: list[str]


def _load_tags(path: Path) -> dict[str, TrackTags]:
    """track id -> duration and raw tags from autotagging.tsv."""
    tags: dict[str, TrackTags] = {}
    with path.open() as file:
        next(file)  # skip tsv header
        for parts in _tsv_rows(file):
            # autotagging.tsv columns: track_id, artist_id, album_id, path, duration, tags
            previous = tags.get(parts[0])
            appended = previous.tags + parts[5].split() if previous else parts[5].split()
            duration = float(parts[4])
            tags[parts[0]] = TrackTags(
                duration=previous.duration if previous else duration,
                tags=appended,
            )
    return tags


def _merge_tags(base: dict[str, TrackTags], extra: dict[str, TrackTags]) -> None:
    """Add tags from the mood/theme subset into the base tags."""
    for track_id, entry in extra.items():
        previous = base.get(track_id)
        merged_tags = previous.tags + entry.tags if previous else entry.tags
        base[track_id] = TrackTags(
            duration=previous.duration if previous else entry.duration,
            tags=merged_tags,
        )


def _tsv_rows(file) -> list[list[str]]:
    return [line.rstrip("\n").split("\t") for line in file]


def _map_tags(
    tags: list[str], tag_map: dict[str, dict[str, list[str] | None]]
) -> tuple[list[str], list[str]]:
    genre: list[str] = []
    mood: list[str] = []
    for raw_tag in tags:
        category, _, tag = raw_tag.partition("---")
        key = "mood" if category == "mood/theme" else category
        if key not in ("genre", "mood"):
            continue
        mapped = tag_map.get(key, {}).get(tag.lower())
        if not mapped:
            continue
        out = genre if key == "genre" else mood
        for target in mapped:
            if target not in out:
                out.append(target)
    return genre, mood


def _drop_title_duplicates(rows: list[ManifestRow]) -> list[ManifestRow]:
    """Keep one copy of same title+artist rows, most are re-uploads."""
    seen: set[tuple[str, str]] = set()
    kept = []
    for row in rows:
        key = (row.title.lower(), row.artist.lower())
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def _balance_by_genre(rows: list[ManifestRow], per_genre: int) -> list[ManifestRow]:
    """Dedupe tracks and spread them evenly over genres: a track with three
    genre tags counts toward all three, so rarer genres fill up first."""
    by_genre: dict[str, list[ManifestRow]] = {}
    for row in rows:
        for tag in row.genre:
            by_genre.setdefault(tag, []).append(row)
    selected_ids: set[str] = set()
    selected: list[ManifestRow] = []
    remaining = dict.fromkeys(by_genre, per_genre)
    # round-robin over genres so rare genres keep their share
    for genre in sorted(by_genre):
        for row in by_genre[genre]:
            if remaining[genre] <= 0:
                break
            if row.id in selected_ids:
                continue
            selected_ids.add(row.id)
            selected.append(row)
            for tag in row.genre:
                if tag in remaining:
                    remaining[tag] -= 1
    return selected


def _write_manifest(out_path: Path, rows: list[ManifestRow]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [name for name in ManifestRow.model_fields if name != "id"]
    with out_path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["id", *fields])
        writer.writeheader()
        for row in rows:
            # ids come from stable_id, so re-runs keep the same id
            record = row.model_dump(mode="json")
            record["genre"] = TAG_SEPARATOR.join(row.genre)
            record["mood"] = TAG_SEPARATOR.join(row.mood)
            writer.writerow(record)


def _ensure_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "jamendo_autotagging.tsv": f"{RAW_BASE}/autotagging.tsv",
        "jamendo_moodtheme.tsv": f"{RAW_BASE}/autotagging_moodtheme.tsv",
        "jamendo_meta.tsv": f"{RAW_BASE}/raw.meta.tsv",
    }
    for name, url in files.items():
        target = CACHE_DIR / name
        if target.exists() and target.stat().st_size > 0:
            continue
        print(f"downloading {url} -> {target}")
        urllib.request.urlretrieve(url, target)


def collect_seeds(in_path: Path, out_path: Path, mood_overrides: Path | None = None) -> None:
    """Convert a 'Artist - Title | genre|genre | mood|mood' seed list into a manifest CSV."""
    genres = load_genres()
    moods = load_moods()
    overrides = _load_mood_overrides(mood_overrides)
    rows: list[ManifestRow] = []
    errors: list[str] = []
    for line_number, line in enumerate(in_path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        sections = [part.strip() for part in line.split(" | ")]
        artist, _, title = sections[0].partition(" - ")
        genre_tags = (
            [tag for tag in sections[1].split(TAG_SEPARATOR) if tag] if len(sections) > 1 else []
        )
        mood_tags = (
            [tag for tag in sections[2].split(TAG_SEPARATOR) if tag] if len(sections) > 2 else []
        )
        # knowledge-based mood seeds ride along when the line has no mood section
        override = overrides.get(f"{title.strip().lower()}|{artist.strip().lower()}")
        if override and not mood_tags:
            mood_tags = override
        unknown_genre = [tag for tag in genre_tags if tag not in genres]
        unknown_mood = [tag for tag in mood_tags if tag not in moods]
        if unknown_genre or unknown_mood:
            errors.append(
                f"line {line_number}: unknown genre {unknown_genre} or mood {unknown_mood}"
            )
            continue
        if not artist or not title:
            errors.append(f"line {line_number}: expected 'Artist - Title'")
            continue
        rows.append(
            ManifestRow(
                id=stable_id("seed", artist.strip().lower(), title.strip().lower()),
                title=title.strip(),
                artist=artist.strip(),
                source=Source.YOUTUBE,
                genre=genre_tags,
                mood=mood_tags,
                label_origin=LabelOrigin.AGENT,
                notes="seed line",
            )
        )
    if errors:
        print("seed line errors:")
        print("\n".join(errors))
    _write_manifest(out_path, rows)
    print(f"wrote {len(rows)} seed rows to {out_path}, {len(errors)} line errors")


def _load_mood_overrides(path: Path | None) -> dict[str, list[str]]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text())
    return data.get("moods", {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build collect-stage manifests")
    sub = parser.add_subparsers(dest="command", required=True)

    seeds = sub.add_parser(
        "seeds", help="Convert a 'Artist - Title | tags' seed list into a manifest CSV"
    )
    seeds.add_argument("--in", dest="in_path", type=Path, required=True)
    seeds.add_argument("--out", type=Path, required=True)
    seeds.add_argument("--mood-overrides", type=Path, default=DATA_DIR / "mood_seeds.json")

    jamendo = sub.add_parser("jamendo", help="Balanced music manifest from MTG-Jamendo")
    jamendo.add_argument("--out", type=Path, default=MANIFEST_DIR / "jamendo.csv")
    jamendo.add_argument("--per-genre", type=int, default=800)
    jamendo.add_argument("--duration-min", type=float, default=DEFAULTS["duration_min"])
    jamendo.add_argument("--duration-max", type=float, default=DEFAULTS["duration_max"])

    speech = sub.add_parser("speech", help="Speech manifest from LibriVox on archive.org")
    speech.add_argument("--out", type=Path, default=MANIFEST_DIR / "speech.csv")
    speech.add_argument("--cap", type=int, default=500)
    speech.add_argument("--items", type=int, default=250)
    speech.add_argument("--files-per-item", type=int, default=3)
    speech.add_argument("--page", type=int, default=1)
    speech.add_argument("--duration-min", type=float, default=60.0)
    speech.add_argument("--duration-max", type=float, default=1800.0)

    args = parser.parse_args(argv)
    if args.command == "jamendo":
        _ensure_cache()
        collect_jamendo(
            out_path=args.out,
            per_genre=args.per_genre,
            duration_min=args.duration_min,
            duration_max=args.duration_max,
        )
    elif args.command == "seeds":
        collect_seeds(in_path=args.in_path, out_path=args.out, mood_overrides=args.mood_overrides)
    else:
        collect_librivox(
            out_path=args.out,
            cap=args.cap,
            items=args.items,
            files_per_item=args.files_per_item,
            page=args.page,
            duration_min=args.duration_min,
            duration_max=args.duration_max,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
