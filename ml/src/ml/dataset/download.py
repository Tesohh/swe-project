"""Download stage: fetch audio for each manifest row and flip row status.

Resume rule: every row gets a status record on disk before the first
download attempt and after every terminal outcome, so a killed run
picks up where it stopped and never fetches the same song twice.
"""

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ml.dataset.manifest import ManifestRow, load_manifest
from ml.dataset.progress import eta_string

# status values: "pending" -> "ok" | "error:<reason>"
STATUS_FILE = "download_status.jsonl"


def status_path(audio_dir: Path) -> Path:
    return audio_dir / STATUS_FILE


def load_status(audio_dir: Path) -> dict[str, str]:
    """Row id -> status, read from the status log."""
    path = status_path(audio_dir)
    if not path.exists():
        return {}
    status: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # torn write from a killed run, last full record wins
        if "id" in record and "status" in record:
            status[record["id"]] = record["status"]
    return status


def record_status(audio_dir: Path, row_id: str, status: str) -> None:
    """Append one status record; the last record per id wins on resume."""
    with status_path(audio_dir).open("a") as file:
        file.write(json.dumps({"id": row_id, "status": status}) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download audio for manifest rows via yt-dlp")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument(
        "--limit", type=int, default=None, help="stop after N finished rows this run"
    )
    parser.add_argument("--workers", type=int, default=4, help="parallel downloads")
    args = parser.parse_args(argv)
    args.audio_dir.mkdir(parents=True, exist_ok=True)

    rows = load_manifest(args.manifest).rows
    status = load_status(args.audio_dir)
    pending = [row for row in rows if not is_done(status.get(row.id, ""))]
    if args.limit is not None:
        pending = pending[: args.limit]

    print(f"{len(pending)} rows to download (of {len(rows)})")
    start = time.monotonic()
    done = 0
    errors = 0
    # downloads are I/O-bound, so a pool of workers runs them concurrently;
    # status appends are tiny, so a lock keeps the jsonl log clean
    lock = threading.Lock()

    def worker(row: ManifestRow) -> str:
        result = download_row(row, args.audio_dir)
        with lock:
            record_status(args.audio_dir, row.id, result)
            return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(worker, pending):
            done += 1
            errors += result.startswith("error:")
            if done % 50 == 0 or done == len(pending):
                eta = eta_string(start, done, len(pending))
                print(f"done {done}/{len(pending)}, errors {errors}, eta {eta}", flush=True)
    return 0


def is_done(status: str) -> bool:
    return status == "ok"


def download_row(row: ManifestRow, audio_dir: Path) -> str:
    """Fetch one row with yt-dlp; returns the terminal status string."""
    import yt_dlp

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(audio_dir / f"{row.id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": 50 * 1024 * 1024,
        **({} if row.url else {"default_search": "ytsearch1"}),
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([source_for(row)])
        return "ok"
    except yt_dlp.utils.DownloadError as exc:
        return f"error:{str(exc)[:200]}"


def source_for(row: ManifestRow) -> str:
    """Which source to fetch: a direct url, or the yt-dlp search query."""
    if row.url:
        return str(row.url)
    return f"ytsearch1:{row.artist} - {row.title}"


if __name__ == "__main__":
    raise SystemExit(main())
