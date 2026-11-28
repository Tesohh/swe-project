"""Inference stage: score audio files or feature files with a trained checkpoint.

Uses the same AST-native features as training (ml.features): a handful of 10.24 s
windows spread across the track body, each scored and averaged into one track score.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file

from ml.features import audio_to_windows, load_audio
from ml.training.model import MultiTaskAST
from ml.training.train import GENRE_VOCAB, MOOD_VOCAB

DEFAULT_CHECKPOINT = Path("runs/neg_b/best.pt")
INFER_WINDOWS = 6


def load_model(checkpoint_path: Path = DEFAULT_CHECKPOINT, device: str | None = None) -> MultiTaskAST:
    """Load a .pt checkpoint or an exported .safetensors file; refuses mismatched vocabs."""
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint_path = Path(checkpoint_path)
    if checkpoint_path.suffix == ".safetensors":
        config = json.loads(checkpoint_path.with_name("config.json").read_text())
        genres, moods = config["genres"], config["moods"]
        state = load_file(checkpoint_path, device=device)
    else:
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        genres, moods, state = checkpoint.get("genres"), checkpoint.get("moods"), checkpoint["model"]
    if genres != GENRE_VOCAB or moods != MOOD_VOCAB:
        raise ValueError(f"{checkpoint_path} was trained with different genre/mood vocabularies")
    model = MultiTaskAST(n_genre=len(GENRE_VOCAB), n_mood=len(MOOD_VOCAB)).to(device)
    model.load_state_dict(state)
    model.eval()
    return model


def load_windows(audio_path: Path, n_windows: int = INFER_WINDOWS) -> np.ndarray:
    """Audio file -> float16 [n, 1024, 128] windows, same features as the training data."""
    return audio_to_windows(load_audio(audio_path), n_windows)


def score_windows(model: MultiTaskAST, windows: np.ndarray) -> dict:
    """Feature windows [n, 1024, 128] -> per-head scores averaged over the windows."""
    device = next(model.parameters()).device
    batch = torch.from_numpy(windows.astype(np.float32)).to(device)
    with torch.no_grad(), torch.autocast(device.type, dtype=torch.bfloat16):
        outputs = model(batch)
    genre = torch.sigmoid(outputs["genre"].float()).mean(dim=0)
    mood = torch.sigmoid(outputs["mood"].float()).mean(dim=0)
    # unit-length track vector: mean of unit-length window vectors, renormalized,
    # so a plain dot product between two tracks is their cosine similarity
    window_vectors = torch.nn.functional.normalize(outputs["embedding"].float(), dim=-1)
    embedding = torch.nn.functional.normalize(window_vectors.mean(dim=0), dim=-1)
    return {
        "embedding": embedding.cpu().numpy(),
        "p_music": torch.sigmoid(outputs["music"].float()).mean().item(),
        "genre": {GENRE_VOCAB[i]: float(genre[i]) for i in range(len(GENRE_VOCAB))},
        "mood": {MOOD_VOCAB[i]: float(mood[i]) for i in range(len(MOOD_VOCAB))},
        "energy": float(outputs["energy"].float().mean().item()),
        "windows": len(windows),
    }


def predict_file(model: MultiTaskAST, path: Path, top_k: int = 5, mood_threshold: float = 0.3) -> dict:
    """Audio file -> compact prediction: top-k genres, passed-threshold moods."""
    scores = score_windows(model, load_windows(path))
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
    parser.add_argument("files", nargs="+", type=Path, help="audio files or .npy feature windows")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--save-embeddings", type=Path, default=None, help="write track vectors to this .npz"
    )
    args = parser.parse_args(argv)

    model = load_model(args.checkpoint)
    vectors: dict[str, np.ndarray] = {}
    for path in args.files:
        windows = np.load(path) if path.suffix == ".npy" else load_windows(path)
        scores = score_windows(model, windows)
        vectors[path.stem] = scores["embedding"]
        genres = sorted(scores["genre"].items(), key=lambda item: -item[1])[: args.top_k]
        print(f"== {path.name} ({scores['windows']} window(s))")
        print(f"  p(music): {scores['p_music']:.3f}   energy: {scores['energy']:.3f}")
        print("  genre:", ", ".join(f"{name} {p:.2f}" for name, p in genres))
        top_moods = sorted(scores["mood"].items(), key=lambda item: -item[1])[:3]
        print("  mood:  ", ", ".join(f"{name} {p:.2f}" for name, p in top_moods))
    if args.save_embeddings:
        np.savez(args.save_embeddings, names=list(vectors), vectors=np.stack(list(vectors.values())))
        print(f"saved {len(vectors)} embeddings to {args.save_embeddings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
