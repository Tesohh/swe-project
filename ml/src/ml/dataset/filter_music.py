"""Filter stage: drop windows that contain music from non-music (negative) clips.

Talk and ambience videos often carry music intros or beds. The pretrained AudioSet AST
(the backbone's original classifier) scores each stored window; windows whose Music
probability is at or above the threshold are removed from the clip's .npy, and clips
left with too few clean windows are deleted. Resume-safe: a sidecar log lists done ids.
"""

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch

from ml.features import BACKBONE

LOG_NAME = "filter_music.jsonl"


def music_scores(model, windows: np.ndarray, music_id: int, device: str) -> np.ndarray:
    """AudioSet Music probability per window."""
    batch = torch.from_numpy(windows.astype(np.float32)).to(device)
    with torch.no_grad():
        logits = model(batch).logits
    return torch.sigmoid(logits[:, music_id]).cpu().numpy()


def main(argv: list[str] | None = None) -> int:
    from transformers import ASTForAudioClassification

    parser = argparse.ArgumentParser(description="Remove music windows from negative clips")
    parser.add_argument("specs_dir", type=Path)
    parser.add_argument("manifests", nargs="+", type=Path, help="manifest CSVs of negative clips")
    parser.add_argument("--threshold", type=float, default=0.2)
    parser.add_argument("--min-clean", type=int, default=2, help="drop clips with fewer clean windows")
    args = parser.parse_args(argv)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ASTForAudioClassification.from_pretrained(BACKBONE).to(device).eval()
    music_id = next(i for i, label in model.config.id2label.items() if label == "Music")

    log_path = args.specs_dir / LOG_NAME
    done = set()
    if log_path.exists():
        done = {json.loads(line)["id"] for line in log_path.read_text().splitlines() if line.strip()}
    ids = [row["id"] for path in args.manifests for row in csv.DictReader(path.open())]
    kept_clips = dropped_clips = removed_windows = 0
    with log_path.open("a") as log:
        for row_id in ids:
            npy = args.specs_dir / f"{row_id}.npy"
            if row_id in done or not npy.exists():
                continue
            windows = np.load(npy)
            scores = music_scores(model, windows, music_id, device)
            clean = scores < args.threshold
            removed_windows += int((~clean).sum())
            if clean.sum() < args.min_clean:
                npy.unlink()
                dropped_clips += 1
            else:
                if not clean.all():
                    np.save(npy, windows[clean])
                kept_clips += 1
            log.write(json.dumps({"id": row_id, "total": len(windows), "kept": int(clean.sum())}) + "\n")
            log.flush()
    print(
        f"kept {kept_clips} clips, dropped {dropped_clips} clips, "
        f"removed {removed_windows} music windows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
