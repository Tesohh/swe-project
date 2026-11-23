"""Download stage: fetch audio for each manifest row and flip row status.

Resume rule: every row gets a status record on disk before the first
download attempt and after every terminal outcome, so a killed run
picks up where it stopped and never fetches the same song twice.
"""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from ml.dataset.manifest import ManifestRow, load_manifest

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
    parser.add_argument("--limit", type=int, default=None, help="stop after N finished rows this run")
    args = parser.parse_args(argv)
    args.audio_dir.mkdir(parents=True, exist_ok=True)

    rows = load_manifest(args.manifest).rows
    status = load_status(args.audio_dir)
    finished = 0
    for row in rows:
        if args.limit is not None and finished >= args.limit:
            break
        if is_done(status.get(row.id, "")):
            continue
        record_status(args.audio_dir, row.id, "pending")
        result = download_row(row, args.audio_dir)
        record_status(args.audio_dir, row.id, result)
        finished += 1
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


def build_ydl_options(target_dir: Path, row: ManifestRow) -> dict:
    """yt-dlp options: audio only, mono-able re-encode kept for the preprocess stage."""
    return {
        "format": "bestaudio/best",
        "outtmpl": str(target_dir / f"{row.id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": 50 * 1024 * 1024,
    }


def source_for(row: ManifestRow) -> str:
    """Which source to fetch: a direct url, or the yt-dlp search query."""
    if row.url:
        return str(row.url)
    return f"ytsearch1:{row.artist} - {row.title}"


if __name__ == "__main__":
    raise SystemExit(main())

