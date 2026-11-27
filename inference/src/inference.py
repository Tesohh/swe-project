import argparse
import json
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file

from src.features import audio_to_windows, load_audio
from src.model import MultiTaskAST

DEFAULT_REPO = "tesohh/music-tagger-ast"
DEFAULT_REVISION = "bebf3a602b3e3d13334724c6380ca2cc8968ee76"
INFER_WINDOWS = 6


def load_model(checkpoint_path: Path, device: str | None = None) -> MultiTaskAST:
    """Load a .pt checkpoint or an exported .safetensors file (with config.json beside it)."""
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint_path = Path(checkpoint_path)
    if checkpoint_path.suffix == ".safetensors":
        config = json.loads(checkpoint_path.with_name("config.json").read_text())
        genres, moods = config["genres"], config["moods"]
        state = load_file(checkpoint_path, device=device)
    else:
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        genres, moods, state = checkpoint["genres"], checkpoint["moods"], checkpoint["model"]
    model = MultiTaskAST(n_genre=len(genres), n_mood=len(moods), pretrained=False).to(device)
    model.load_state_dict(state)
    model.genres, model.moods = list(genres), list(moods)
    model.eval()
    return model


def load_from_hub(repo: str = DEFAULT_REPO, revision: str = DEFAULT_REVISION, device: str | None = None) -> MultiTaskAST:
    """Download a pinned model revision from Hugging Face and load it."""
    from huggingface_hub import snapshot_download

    folder = snapshot_download(repo, revision=revision)
    return load_model(Path(folder) / "model.safetensors", device)


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
        "genre": {name: float(genre[i]) for i, name in enumerate(model.genres)},
        "mood": {name: float(mood[i]) for i, name in enumerate(model.moods)},
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
    parser = argparse.ArgumentParser(description="Score audio files with the tagger model")
    parser.add_argument("files", nargs="+", type=Path, help="audio files or .npy feature windows")
    parser.add_argument("--checkpoint", type=Path, default=None, help="local .pt or .safetensors")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--save-embeddings", type=Path, default=None, help="write track vectors to this .npz")
    args = parser.parse_args(argv)

    model = load_model(args.checkpoint) if args.checkpoint else load_from_hub()
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
