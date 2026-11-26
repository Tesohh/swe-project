"""Clean the agent seed list: fix malformed lines, merge duplicates, correct bucket labels.

The expand_* scripts appended lists labelled by one bucket key and deduped on the whole
line, so the same song landed twice (with and without apostrophes) and whole artists got
the wrong genre. This stage rewrites agent_seeds.txt in place (the old file is kept as
agent_seeds.txt.bak) and can rename already-downloaded audio to the surviving ids so no
song needs a second download.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from ml.dataset.download import audio_file_for
from ml.dataset.manifest import stable_id
from ml.dataset.vocabs import DATA_DIR, load_genres, load_moods

TAG_SEPARATOR = "|"
# child genre -> parent genres it must also carry
IMPLIED_GENRES = {"techno": ["electronic"], "house": ["electronic"]}


def normalize(text: str) -> str:
    """Spelling-insensitive key: lowercase, '&' as 'and', no punctuation, no leading 'the'."""
    text = text.lower().replace("&", "and")
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"[^a-z0-9 ]", "", text).strip()
    text = re.sub(r"^the ", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_song(head: str) -> tuple[str, str]:
    """'Artist - Title' -> (artist, title), tolerating 'Artist - - Title' and 'Artist- Title'."""
    head = re.sub(r"\s*-\s+-\s+", " - ", head)
    if " - " not in head:
        head = re.sub(r"(?<=\w)- (?=\w)", " - ", head, count=1)
    artist, _, title = head.partition(" - ")
    return artist.strip(), title.strip()


def mood_key(artist: str, title: str) -> str:
    """Key format used by mood_seeds.json."""
    return f"{title.lower()}|{artist.lower()}"


def clean(
    lines: list[str],
    overrides: dict,
    mood_seeds: dict,
    exclude: set[tuple[str, str]] = frozenset(),
) -> tuple[list[str], dict, list[str]]:
    """Return (clean lines, old id -> new id renames, human-readable drop notes).

    exclude: normalized (artist, title) pairs that must not become seeds (held-out test songs).
    """
    genres, moods = load_genres(), load_moods()
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    dropped: list[str] = []
    for number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        sections = [part.strip() for part in raw.split(" | ")]
        old_artist, _, old_title = sections[0].partition(" - ")
        artist, title = split_song(sections[0])
        if not artist or not title:
            dropped.append(f"line {number}: no 'Artist - Title': {raw!r}")
            continue
        genre = [t for t in (sections[1].split(TAG_SEPARATOR) if len(sections) > 1 else []) if t]
        mood = [t for t in (sections[2].split(TAG_SEPARATOR) if len(sections) > 2 else []) if t]
        mood += mood_seeds.get(mood_key(old_artist.strip(), old_title.strip()), [])
        mood += mood_seeds.get(mood_key(artist, title), [])
        if (normalize(artist), normalize(title)) in exclude:
            dropped.append(f"line {number}: held-out test song: {artist} - {title}")
            continue
        groups[(normalize(artist), normalize(title))].append(
            {
                "artist": artist,
                "title": title,
                "old_id": stable_id("seed", old_artist.strip().lower(), old_title.strip().lower()),
                "genre": genre,
                "mood": mood,
                "number": number,
            }
        )

    out: list[str] = []
    renames: dict[str, str] = {}
    for (artist_key, title_key), members in groups.items():
        # keep the best-punctuated spelling, e.g. "Don't Stop Believin'" over "Dont Stop Believin"
        keep = max(members, key=lambda m: (len(re.findall(r"[^A-Za-z0-9 ]", m["title"])), m["number"]))
        genre = list(dict.fromkeys(g for m in members for g in m["genre"]))
        mood = list(dict.fromkeys(t for m in members for t in m["mood"]))
        song_override = overrides["songs"].get(f"{artist_key}|{title_key}")
        artist_override = overrides["artists"].get(artist_key)
        genre = song_override or artist_override or genre
        for child, parents in IMPLIED_GENRES.items():
            if child in genre:
                genre += [p for p in parents if p not in genre]
        genre = [g for g in genre if g in genres]
        mood = [t for t in mood if t in moods]
        if not genre:
            dropped.append(f"no valid genre: {keep['artist']} - {keep['title']}")
            continue
        line = f"{keep['artist']} - {keep['title']} | {TAG_SEPARATOR.join(genre)}"
        if mood:
            line += f" | {TAG_SEPARATOR.join(mood)}"
        out.append((keep["number"], line))
        new_id = stable_id("seed", keep["artist"].lower(), keep["title"].lower())
        for member in members:
            if member["old_id"] != new_id:
                renames[member["old_id"]] = new_id
    out.sort()
    return [line for _, line in out], renames, dropped


def apply_renames(audio_dir: Path, renames: dict[str, str]) -> tuple[int, int]:
    """Rename audio to the surviving id when it has none; return (renamed, orphaned)."""
    renamed = orphaned = 0
    for old_id, new_id in renames.items():
        old_file = audio_file_for(audio_dir, old_id)
        if old_file is None:
            continue
        if audio_file_for(audio_dir, new_id) is None:
            old_file.rename(old_file.with_name(f"{new_id}{old_file.suffix}"))
            renamed += 1
        else:
            orphaned += 1  # the surviving id already has audio; the old copy is now unreferenced
    return renamed, orphaned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean and dedupe the agent seed list")
    parser.add_argument("--seeds", type=Path, default=DATA_DIR / "agent_seeds.txt")
    parser.add_argument("--overrides", type=Path, default=DATA_DIR / "seed_genre_overrides.json")
    parser.add_argument("--mood-seeds", type=Path, default=DATA_DIR / "mood_seeds.json")
    parser.add_argument("--test-dir", type=Path, default=DATA_DIR, help="folder with test_songs*.jsonl")
    parser.add_argument("--audio-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--write", action="store_true", help="rewrite the seed file (keeps .bak)")
    parser.add_argument("--rename-audio", action="store_true", help="rename audio to surviving ids")
    args = parser.parse_args(argv)

    overrides = json.loads(args.overrides.read_text())
    overrides = {
        "artists": {normalize(k): v for k, v in overrides.get("artists", {}).items()},
        "songs": {
            "|".join(normalize(part) for part in k.split("|")): v
            for k, v in overrides.get("songs", {}).items()
        },
    }
    mood_seeds = json.loads(args.mood_seeds.read_text()).get("moods", {})
    lines = args.seeds.read_text().splitlines()
    exclude = set()
    for path in sorted(args.test_dir.glob("test_songs*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                artist, _, title = json.loads(line)["query"].partition(" - ")
                exclude.add((normalize(artist), normalize(title)))
    cleaned, renames, dropped = clean(lines, overrides, mood_seeds, exclude)

    print(f"{len(lines)} lines -> {len(cleaned)} songs, {len(renames)} spellings merged")
    print("\n".join(dropped))
    if args.write:
        backup = args.seeds.with_name(args.seeds.name + ".bak")
        if not backup.exists():
            backup.write_text("\n".join(lines) + "\n")
        args.seeds.write_text("\n".join(cleaned) + "\n")
        print(f"wrote {args.seeds}")
    if args.rename_audio:
        renamed, orphaned = apply_renames(args.audio_dir, renames)
        print(f"audio renamed: {renamed}, old copies left unreferenced: {orphaned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
