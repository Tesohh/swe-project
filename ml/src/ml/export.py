"""Export a checkpoint to a Hugging Face release folder (safetensors, config, model card)."""

import argparse
import json
import shutil
from pathlib import Path

import torch
from safetensors.torch import save_file

from ml.features import BACKBONE, N_MELS, SAMPLE_RATE, WINDOW_FRAMES
from ml.inference import DEFAULT_CHECKPOINT, INFER_WINDOWS

MODEL_CARD = Path(__file__).resolve().parents[2] / "hf" / "MODEL_CARD.md"


def export(checkpoint: Path, out_dir: Path) -> None:
    ckpt = torch.load(checkpoint, map_location="cpu", weights_only=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    weights = {k: v.contiguous() for k, v in ckpt["model"].items()}
    save_file(weights, out_dir / "model.safetensors", metadata={"format": "pt"})
    config = {
        "architecture": "MultiTaskAST",
        "backbone": BACKBONE,
        "genres": ckpt["genres"],
        "moods": ckpt["moods"],
        "sample_rate": SAMPLE_RATE,
        "n_mels": N_MELS,
        "window_frames": WINDOW_FRAMES,
        "inference_windows": INFER_WINDOWS,
        "embedding_size": 768,
        "val_metrics": ckpt["metrics"],
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    shutil.copy(MODEL_CARD, out_dir / "README.md")
    print(f"wrote {len(weights)} tensors and config to {out_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a checkpoint for Hugging Face")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--out-dir", type=Path, default=Path("hf_release"))
    args = parser.parse_args(argv)
    export(args.checkpoint, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
