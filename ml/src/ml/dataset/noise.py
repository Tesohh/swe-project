"""Noise stage: non-music negatives for the music head.

Two sources, both written straight into the raw audio dir plus a manifest CSV:
- ESC-50 environmental clips (animals, weather, household, urban sounds; no music)
- synthetic clips (silence, noise colours, tones, sweeps, clicks, modulated noise)
The artist field holds the sound class, so artist-grouped validation holds out classes.
"""

import argparse
import csv
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

from ml.dataset.collect import DATA_DIR, MANIFEST_DIR, _write_manifest
from ml.dataset.manifest import ManifestRow, stable_id
from ml.dataset.vocabs import AudioType, LabelOrigin, Source

ESC50_ZIP_URL = "https://github.com/karoldvl/ESC-50/archive/master.zip"

SYNTH_RATE = 16000
SYNTH_SECONDS = 12
MIN_SECONDS = 12


def collect_esc50(raw_dir: Path, cache_dir: Path, per_category: int = 14) -> list[ManifestRow]:
    """Build long negatives from ESC-50: 4 different clips of one class joined per clip.

    A raw 5 s clip leaves half of an AST window as padding, which the model then learns
    as a "not music" cue. Joining different clips (not one clip looped) fills the window
    without padding and without a repetition cue.
    """
    import librosa

    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / "esc50.zip"
    if not archive.exists():
        urllib.request.urlretrieve(ESC50_ZIP_URL, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(cache_dir)
    root = cache_dir / "ESC-50-master"
    by_category: dict[str, list[str]] = {}
    for record in csv.DictReader((root / "meta" / "esc50.csv").open()):
        by_category.setdefault(record["category"], []).append(record["filename"])
    rows = []
    for category, names in sorted(by_category.items()):
        for i in range(per_category):
            row_id = stable_id("esc50_cat", category, str(i))
            rng = np.random.default_rng(int(row_id[:8], 16))
            order = [names[j] for j in rng.permutation(len(names))]
            target = raw_dir / f"{row_id}.wav"
            parts, picked = [], []
            for name in order:
                audio, _ = librosa.load(root / "audio" / name, sr=SYNTH_RATE, mono=True)
                parts.append(_trim_silence(audio) * 10 ** rng.uniform(-0.3, 0.3))
                picked.append(name)
                # at least 4 clips, and at least 12 s so one window has no padding
                if len(parts) >= 4 and sum(map(len, parts)) >= MIN_SECONDS * SYNTH_RATE:
                    break
            if not target.exists():
                sf.write(target, np.clip(_join(parts), -1, 1).astype(np.float32), SYNTH_RATE)
            rows.append(
                ManifestRow(
                    id=row_id,
                    query=f"esc50 {category} {i}",
                    title=f"{category} {i}",
                    artist=f"esc50 {category}",
                    source=Source.NOISE,
                    audio_type=AudioType.NOISE,
                    label_origin=LabelOrigin.DATASET_TAG,
                    notes=f"esc50 category: {category}, clips: {' '.join(picked)}",
                )
            )
    return rows


def _trim_silence(audio: np.ndarray, threshold: float = 1e-4) -> np.ndarray:
    """Cut the digital-silence padding ESC-50 adds to short clips."""
    loud = np.flatnonzero(np.abs(audio) > threshold)
    return audio[loud[0] : loud[-1] + 1] if len(loud) else audio


def _join(parts: list[np.ndarray], fade_seconds: float = 0.1) -> np.ndarray:
    """Concatenate clips with short linear crossfades."""
    fade = int(fade_seconds * SYNTH_RATE)
    out = parts[0]
    for part in parts[1:]:
        n = min(fade, len(out), len(part))
        ramp = np.linspace(0, 1, n)
        out = np.concatenate([out[:-n], out[-n:] * (1 - ramp) + part[:n] * ramp, part[n:]])
    return out


def _noise(rng: np.random.Generator, n: int, exponent: float) -> np.ndarray:
    """Noise with a 1/f^exponent power spectrum (0 white, 1 pink, 2 brown)."""
    freqs = np.fft.rfftfreq(n)
    freqs[0] = 1
    spectrum = rng.normal(size=len(freqs)) + 1j * rng.normal(size=len(freqs))
    x = np.fft.irfft(spectrum / freqs ** (exponent / 2), n)
    return x / np.abs(x).max()


def synth_clip(kind: str, rng: np.random.Generator) -> np.ndarray:
    """One synthetic non-music waveform in [-1, 1]."""
    n = SYNTH_RATE * SYNTH_SECONDS
    t = np.arange(n) / SYNTH_RATE
    level = 10 ** rng.uniform(-2.5, -0.3)
    if kind == "silence":
        return np.zeros(n)
    if kind == "hiss":
        return rng.normal(size=n) * 10 ** rng.uniform(-4, -2.5)
    if kind in ("white_noise", "pink_noise", "brown_noise"):
        exponent = {"white_noise": 0, "pink_noise": 1, "brown_noise": 2}[kind]
        return _noise(rng, n, exponent) * level
    if kind == "sine":
        return level * np.sin(2 * np.pi * rng.uniform(50, 6000) * t)
    if kind == "sweep":
        f0, rate = rng.uniform(100, 500), rng.uniform(20, 400)
        return level * np.sin(2 * np.pi * (f0 + rate * t) * t)
    if kind == "square":
        return level * np.sign(np.sin(2 * np.pi * rng.uniform(50, 2000) * t))
    if kind == "clicks":
        out = np.zeros(n)
        out[:: int(rng.uniform(0.2, 1.5) * SYNTH_RATE)] = level
        return out
    if kind == "am_noise":
        am = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.3, 6) * t)
        return _noise(rng, n, rng.uniform(0, 2)) * level * am
    if kind == "dual_tone":
        f1, f2 = rng.uniform(300, 1700, size=2)
        return level * 0.5 * (np.sin(2 * np.pi * f1 * t) + np.sin(2 * np.pi * f2 * t))
    raise ValueError(kind)


SYNTH_KINDS = [
    "silence", "hiss", "white_noise", "pink_noise", "brown_noise",
    "sine", "sweep", "square", "clicks", "am_noise", "dual_tone",
]  # fmt: skip


def collect_synthetic(raw_dir: Path, per_kind: int) -> list[ManifestRow]:
    """Generate synthetic clips into raw_dir and return their manifest rows."""
    rows = []
    for kind in SYNTH_KINDS:
        for i in range(per_kind):
            row_id = stable_id("synthetic", kind, str(i))
            target = raw_dir / f"{row_id}.wav"
            if not target.exists():
                rng = np.random.default_rng(int(row_id[:8], 16))
                sf.write(target, synth_clip(kind, rng).astype(np.float32), SYNTH_RATE)
            rows.append(
                ManifestRow(
                    id=row_id,
                    query=f"synthetic {kind} {i}",
                    title=f"{kind} {i}",
                    artist=f"synthetic {kind}",
                    source=Source.SYNTHETIC,
                    audio_type=AudioType.NOISE,
                    label_origin=LabelOrigin.MEASURED,
                    notes=f"synthetic kind: {kind}",
                )
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build non-music noise clips and manifest")
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--cache-dir", type=Path, default=DATA_DIR / "esc50")
    parser.add_argument("--out", type=Path, default=MANIFEST_DIR / "noise_v3.csv")
    parser.add_argument("--synthetic-per-kind", type=int, default=30)
    args = parser.parse_args(argv)

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    rows = collect_esc50(args.raw_dir, args.cache_dir)
    rows += collect_synthetic(args.raw_dir, args.synthetic_per_kind)
    _write_manifest(args.out, rows)
    print(f"wrote {len(rows)} noise rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
