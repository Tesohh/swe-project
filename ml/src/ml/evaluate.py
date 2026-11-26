"""Score a checkpoint on the held-out test songs (data/test_songs.jsonl).

Each test song is downloaded once into data/test_audio (never into data/raw, so it
cannot leak into training), scored the way inference scores tracks, and compared with
its expected primary genre.
"""

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from ml.dataset.vocabs import DATA_DIR
from ml.inference import INFER_WINDOWS, DEFAULT_CHECKPOINT, load_model, load_windows, score_windows

TEST_SONGS = DATA_DIR / "test_songs.jsonl"
TEST_AUDIO = DATA_DIR / "test_audio"
TEST_FEATURES = DATA_DIR / "test_features"  # cached windows, so reruns skip decoding
MIN_SECONDS, MAX_SECONDS = 60, 540


def load_songs(path: Path = TEST_SONGS) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def fetch_missing(songs: list[dict], audio_dir: Path = TEST_AUDIO) -> list[str]:
    """Download test songs that are not on disk yet; returns the files that failed."""
    import yt_dlp

    audio_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    for song in songs:
        if list(audio_dir.glob(f"{song['file']}.*")):
            continue
        options = {
            "format": "bestaudio/best",
            "outtmpl": str(audio_dir / f"{song['file']}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "max_filesize": 50 * 1024 * 1024,
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(f"ytsearch1:{song['query']}", download=True)["entries"][0]
        except Exception as exc:  # noqa: BLE001 - one bad search must not stop the rest
            print(f"download failed: {song['query']}: {str(exc)[:80]}")
            failed.append(song["file"])
            continue
        duration = info.get("duration") or 0
        print(f"{song['query'][:46]:46} -> {info.get('title', '')[:56]} ({duration:.0f}s)")
        # a wrong search hit is usually a mix, a live set or a snippet: reject by length
        if not MIN_SECONDS <= duration <= MAX_SECONDS:
            for leftover in audio_dir.glob(f"{song['file']}.*"):
                leftover.unlink()
            print("  rejected: duration outside the expected range")
            failed.append(song["file"])
    return failed


def cached_windows(song: dict, audio: Path, refresh: bool = False) -> np.ndarray:
    """A test song's feature windows, computed once from the audio and then read from disk."""
    cache = TEST_FEATURES / f"{song['file']}.npy"
    if cache.exists() and not refresh:
        windows = np.load(cache)
        if len(windows) == INFER_WINDOWS:
            return windows
    TEST_FEATURES.mkdir(exist_ok=True)
    windows = load_windows(audio)
    np.save(cache, windows)
    return windows


def evaluate(checkpoint: Path, songs: list[dict], verbose: bool = True, refresh: bool = False) -> dict:
    start = time.monotonic()
    model = load_model(checkpoint)
    top1 = top3 = scored = 0
    by_genre: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for song in songs:
        files = list(TEST_AUDIO.glob(f"{song['file']}.*"))
        if not files:
            continue
        scores = score_windows(model, cached_windows(song, files[0], refresh))
        ranked = [g for g, _ in sorted(scores["genre"].items(), key=lambda kv: -kv[1])]
        hit1, hit3 = ranked[0] == song["expect"], song["expect"] in ranked[:3]
        scored += 1
        top1 += hit1
        top3 += hit3
        by_genre[song["expect"]][0] += hit1
        by_genre[song["expect"]][1] += 1
        if verbose and not hit1:
            top = ", ".join(f"{g} {scores['genre'][g]:.2f}" for g in ranked[:3])
            print(f"  miss: {song['query'][:44]:44} expect {song['expect']:10} got {top}")
    print(f"scored in {time.monotonic() - start:.0f}s")
    print(f"test songs: top-1 {top1}/{scored} ({top1 / max(scored, 1):.0%})  top-3 {top3}/{scored} ({top3 / max(scored, 1):.0%})")
    return {"top1": top1 / max(scored, 1), "top3": top3 / max(scored, 1), "n": scored}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a checkpoint on the test songs")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--refresh", action="store_true", help="recompute cached test features")
    parser.add_argument("--fetch", action="store_true", help="download missing test audio first")
    args = parser.parse_args(argv)
    songs = load_songs()
    if args.fetch:
        fetch_missing(songs)
    evaluate(args.checkpoint, songs, refresh=args.refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
