"""Preprocess stage: audio files -> log-mel spectrogram tiles + energy values.

Input:  the raw audio directory produced by the download stage.
Output: one .npy per song in the preprocessed dir, float32 [mel, frames] tiles
        concatenated along the frame axis, plus a .json sidecar with metadata.
        The trainer slices the tiles into fixed windows later.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ml.dataset.progress import eta_string

# extensions the download stage can produce
AUDIO_EXTENSIONS = ["mp3", "m4a", "webm", "opus", "ogg", "wav", "flac"]

SAMPLE_RATE = 22050
N_MELS = 96
N_FFT = 1024
HOP_LENGTH = 512


def load_audio(path: Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Load one audio file as mono float samples in [-1, 1]."""
    import librosa

    audio, _ = librosa.load(str(path), sr=sample_rate, mono=True)
    return audio


def log_mel_spectrogram(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Log-mel spectrogram, shape [n_mels, frames], decibel scale, log(clamp) floor."""
    import librosa

    mel = librosa.feature.melspectrogram(
        y=audio, sr=sample_rate, n_fft=N_FFT, hop_length=HOP_LENGTH, n_mels=N_MELS
    )
    return librosa.power_to_db(mel, ref=np.max)


def measure_energy(audio: np.ndarray) -> float:
    """Recorded loudness as one number in [0, 1]: mean RMS dB, min-max squashed.

    A rough proxy till the energy head trains: silence ~0, loud masters ~1.
    """
    import librosa

    rms = librosa.feature.rms(y=audio, frame_length=2048, hop_length=512)
    db = librosa.amplitude_to_db(rms, ref=1.0)
    mean_db = float(np.mean(db))
    # -60 dB and 0 dB map to 0 and 1 over a working loudness window
    return float(np.clip((mean_db + 60.0) / 60.0, 0.0, 1.0))


def preprocess_row(audio_path: Path) -> tuple[np.ndarray, float, float]:
    """audio file -> (spectrogram [n_mels, frames], energy, duration_s)."""
    audio = load_audio(audio_path)
    spec = log_mel_spectrogram(audio)
    energy = measure_energy(audio)
    duration = len(audio) / SAMPLE_RATE
    return spec, energy, duration


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preprocess downloaded audio into spectrogram tensors"
    )
    parser.add_argument("audio_dir", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None, help="stop after N files this run")
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    sidecar = args.out_dir / "preprocessed.jsonl"
    done = set()
    if sidecar.exists():
        done = {json.loads(line)["id"] for line in sidecar.read_text().splitlines() if line.strip()}

    audio_files = sorted(p for p in args.audio_dir.iterdir() if p.suffix.lstrip(".") in AUDIO_EXTENSIONS)
    pending = [p for p in audio_files if p.stem not in done]
    print(f"{len(pending)} files to preprocess (of {len(audio_files)} on disk)")
    start = time.monotonic()
    processed = 0
    failed = 0
    for audio_path in pending:
        row_id = audio_path.stem
        try:
            spec, energy, duration = preprocess_row(audio_path)
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the run
            print(f"{row_id}: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
            continue
        np.save(args.out_dir / f"{row_id}.npy", spec.astype(np.float32))
        with sidecar.open("a") as file:
            file.write(
                json.dumps(
                    {
                        "id": row_id,
                        "shape": list(spec.shape),
                        "energy": energy,
                        "duration_s": duration,
                    }
                )
                + "\n"
            )
        processed += 1
        done_here = processed + failed
        if done_here % 20 == 0 or done_here == len(pending):
            print(
                f"done {done_here}/{len(pending)}, failed {failed}, "
                f"eta {eta_string(start, done_here, len(pending))}",
                flush=True,
            )
        if args.limit is not None and processed >= args.limit:
            break
    print(f"preprocessed {processed} new files to {args.out_dir} ({failed} failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
