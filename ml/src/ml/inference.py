"""Inference stage: score audio files or spectrograms with a layered checkpoint.

Loads the full head chain (genre/mood/music/energy), splits long tracks into
AST_FRAMES windows, and averages per-window predictions into one track score.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from ml.training.model import MultiTaskAST
from ml.training.train import AST_FRAMES, AST_MEL_BINS, GENRE_VOCAB, MOOD_VOCAB

DEFAULT_CHECKPOINT = Path("runs/seed_head_ft/last.pt")


def load_model(checkpoint_path: Path = DEFAULT_CHECKPOINT, device: str | None = None) -> MultiTaskAST:
    """Load the layered checkpoint into the multi-task model, eval mode."""
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model = MultiTaskAST(n_genre=len(GENRE_VOCAB), n_mood=len(MOOD_VOCAB)).to(device)
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model


def load_spectrogram(audio_path: Path) -> np.ndarray:
    """Audio file -> log-mel spectrogram, same settings as the training data."""
    from ml.dataset.preprocess import load_audio, log_mel_spectrogram

    return log_mel_spectrogram(load_audio(audio_path))


def _to_grid(spec: np.ndarray) -> torch.Tensor:
    """One spectrogram [mels, frames] -> [frames, mels] tensor on the AST grid."""
    spec = torch.from_numpy(np.ascontiguousarray(spec[:AST_MEL_BINS, :AST_FRAMES].T))
    grid = torch.full((AST_FRAMES, AST_MEL_BINS), -80.0)
    grid[: spec.shape[0], : spec.shape[1]] = spec
    return grid


def score_spectrogram(model: MultiTaskAST, spec: np.ndarray) -> dict:
    """Spectrogram -> averaged per-head scores for the whole track.

    spec: [n_mels, frames]; long tracks are tiled into AST_FRAMES windows,
    and every head is averaged over windows (sigmoid for the BCE heads).
    """
    device = next(model.parameters()).device
    frames = spec.shape[-1]
    tiles = [spec[:, start : start + AST_FRAMES] for start in range(0, frames, AST_FRAMES)]
    batched = torch.stack([_to_grid(tile) for tile in tiles]).to(device)

    with torch.no_grad():
        outputs = model(batched)

    music = torch.sigmoid(outputs["music"]).mean().item()
    genre = torch.sigmoid(outputs["genre"]).mean(dim=0)
    mood = torch.sigmoid(outputs["mood"]).mean(dim=0)
    energy = float(outputs["energy"].mean().item())
    return {
        "p_music": music,
        "genre": {GENRE_VOCAB[i]: float(genre[i]) for i in range(len(GENRE_VOCAB))},
        "mood": {MOOD_VOCAB[i]: float(mood[i]) for i in range(len(MOOD_VOCAB))},
        "energy": energy,
        "windows": len(tiles),
    }


def predict_file(model: MultiTaskAST, path: Path, top_k: int = 5, mood_threshold: float = 0.3) -> dict:
    """Audio file -> compact prediction: top-k genres, passed-threshold moods."""
    spec = load_spectrogram(path)
    scores = score_spectrogram(model, spec)
    genres = sorted(scores["genre"].items(), key=lambda item: -item[1])[:top_k]
    moods = [(name, p) for name, p in scores["mood"].items() if p >= mood_threshold]
    moods.sort(key=lambda item: -item[1])
    return {
        "p_music": round(scores["p_music"], 3),
        "genre": genres,
        "mood": moods,
        "energy": round(scores["energy"], 3),
        "windows": scores["windows"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score audio files with the layered model")
    parser.add_argument("files", nargs="+", type=Path, help="audio files or .npy spectrograms")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)

    model = load_model(args.checkpoint)
    for path in args.files:
        if path.suffix == ".npy":
            spec = np.load(path)
        else:
            spec = load_spectrogram(path)
        scores = score_spectrogram(model, spec)
        genres = sorted(scores["genre"].items(), key=lambda item: -item[1])[: args.top_k]
        print(f"== {path.name} ({scores['windows']} window(s))")
        print(f"  p(music): {scores['p_music']:.3f}   energy: {scores['energy']:.3f}")
        print("  genre:", ", ".join(f"{name} {p:.2f}" for name, p in genres))
        top_moods = sorted(scores["mood"].items(), key=lambda item: -item[1])[:3]
        print("  mood:  ", ", ".join(f"{name} {p:.2f}" for name, p in top_moods))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
