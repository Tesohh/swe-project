"""Preprocess stage: audio files -> AST-native feature windows + energy values.

Input:  the raw audio directory produced by the download stage.
Output: one .npy per song: float16 [n_windows, 1024, 128] AST fbank windows taken
        evenly across the track body (see ml.features), plus a preprocessed.jsonl
        sidecar with energy and duration. The trainer picks a random window per step.
"""

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ml.dataset.progress import eta_string
from ml.features import SAMPLE_RATE, audio_to_windows, load_audio

# extensions the download stage can produce
AUDIO_EXTENSIONS = ["mp3", "m4a", "webm", "opus", "ogg", "wav", "flac"]
N_WINDOWS = 3


def measure_energy(audio: np.ndarray) -> float:
    """Recorded loudness as one number in [0, 1]: mean RMS dB, min-max squashed.

    A rough proxy (it tracks mastering loudness more than musical energy):
    silence ~0, loud masters ~1.
    """
    import librosa

    rms = librosa.feature.rms(y=audio, frame_length=2048, hop_length=512)
    db = librosa.amplitude_to_db(rms, ref=1.0)
    mean_db = float(np.mean(db))
    # -60 dB and 0 dB map to 0 and 1 over a working loudness window
    return float(np.clip((mean_db + 60.0) / 60.0, 0.0, 1.0))


def preprocess_row(audio_path: Path, out_dir: Path, n_windows: int) -> dict:
    """Audio file -> saved window tensor; returns the sidecar record."""
    audio = load_audio(audio_path)
    if len(audio) < SAMPLE_RATE:
        raise ValueError(f"under 1 s of audio ({len(audio)} samples)")
    windows = audio_to_windows(audio, n_windows)
    np.save(out_dir / f"{audio_path.stem}.npy", windows)
    return {
        "id": audio_path.stem,
        "windows": int(windows.shape[0]),
        "energy": measure_energy(audio),
        "duration_s": len(audio) / SAMPLE_RATE,
    }


def _work(args: tuple[Path, Path, int]) -> tuple[str, dict | str]:
    audio_path, out_dir, n_windows = args
    try:
        return audio_path.stem, preprocess_row(audio_path, out_dir, n_windows)
    except Exception as exc:  # noqa: BLE001 - one bad file must not kill the run
        return audio_path.stem, f"{type(exc).__name__}: {str(exc)[:120]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preprocess downloaded audio into AST windows")
    parser.add_argument("audio_dir", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None, help="stop after N files this run")
    parser.add_argument("--workers", type=int, default=8, help="parallel decoding processes")
    parser.add_argument("--windows", type=int, default=N_WINDOWS, help="windows saved per track")
    parser.add_argument(
        "--only", type=Path, default=None, help="text file of ids (one per line) to restrict to"
    )
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    sidecar = args.out_dir / "preprocessed.jsonl"
    done = set()
    if sidecar.exists():
        done = {json.loads(line)["id"] for line in sidecar.read_text().splitlines() if line.strip()}

    audio_files = sorted(
        p for p in args.audio_dir.iterdir() if p.suffix.lstrip(".") in AUDIO_EXTENSIONS
    )
    if args.only:
        wanted = {line.strip() for line in args.only.read_text().splitlines() if line.strip()}
        audio_files = [p for p in audio_files if p.stem in wanted]
    pending = [p for p in audio_files if p.stem not in done]
    if args.limit is not None:
        pending = pending[: args.limit]
    print(f"{len(pending)} files to preprocess (of {len(audio_files)} on disk)")

    start = time.monotonic()
    processed = failed = 0
    jobs = [(p, args.out_dir, args.windows) for p in pending]
    with ProcessPoolExecutor(max_workers=args.workers) as pool, sidecar.open("a") as out:
        for row_id, result in pool.map(_work, jobs, chunksize=4):
            if isinstance(result, str):
                failed += 1
                print(f"{row_id}: {result}", flush=True)
            else:
                out.write(json.dumps(result) + "\n")
                out.flush()
                processed += 1
            finished = processed + failed
            if finished % 20 == 0 or finished == len(pending):
                print(
                    f"done {finished}/{len(pending)}, failed {failed}, "
                    f"eta {eta_string(start, finished, len(pending))}",
                    flush=True,
                )
    print(f"preprocessed {processed} new files to {args.out_dir} ({failed} failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
