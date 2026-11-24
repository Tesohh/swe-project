"""Training loop for the multi-task audio model."""

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from ml.training.model import MultiTaskAST

# fixed label spaces; heads tie to these indexes, so never reorder this list
GENRE_VOCAB = [
    "rock",
    "pop",
    "jazz",
    "blues",
    "electronic",
    "techno",
    "house",
    "ambient",
    "folk",
    "world",
    "hip_hop",
    "rap",
    "rnb",
    "soul",
    "funk",
    "metal",
    "punk",
    "classical",
    "latin",
    "country",
    "reggae",
    "experimental",
]
MOOD_VOCAB = [
    "calm",
    "sad",
    "happy",
    "party",
    "energetic",
    "dark",
    "romantic",
    "dreamy",
    "melancholic",
    "dramatic",
]


class SpecDataset(Dataset):
    """Manifest rows joined with preprocessed spectrograms on disk."""

    def __init__(self, manifest_path: Path, specs_dir: Path):
        self.specs_dir = specs_dir
        self.rows = []
        for line in manifest_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            # only rows that have a spectrogram on disk can enter training
            if (specs_dir / f"{row['id']}.npy").exists():
                self.rows.append(row)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[np.ndarray, dict]:
        spec = np.load(self.specs_dir / f"{self.rows[index]['id']}.npy")
        return spec, self.rows[index]


def collate(batch, genre_vocab=GENRE_VOCAB, mood_vocab=MOOD_VOCAB) -> dict[str, torch.Tensor]:
    """Pad spectrograms along the frame axis with the -80 dB silence floor."""
    n_mels = batch[0][0].shape[0]
    max_frames = max(spec.shape[-1] for spec, _ in batch)
    specs = torch.full((len(batch), n_mels, max_frames), -80.0)
    for i, (spec, _) in enumerate(batch):
        specs[i, :, : spec.shape[-1]] = torch.from_numpy(spec.copy())
    music = torch.tensor(
        [1.0 if row.get("audio_type", "music") == "music" else 0.0 for _, row in batch]
    )
    genre = torch.zeros(len(batch), len(genre_vocab))
    mood = torch.zeros(len(batch), len(mood_vocab))
    for i, (_, row) in enumerate(batch):
        for tag in row.get("genre", []):
            if tag in genre_vocab:
                genre[i, genre_vocab.index(tag)] = 1.0
        for tag in row.get("mood", []):
            if tag in mood_vocab:
                mood[i, mood_vocab.index(tag)] = 1.0
    return {"specs": specs, "music": music, "genre": genre, "mood": mood}


def _format_duration(seconds: float) -> str:
    """ETA string like 12:34 or 1:02:03."""
    minutes, secs = divmod(int(seconds + 0.5), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def evaluate(model: MultiTaskAST, loader: DataLoader) -> dict[str, float]:
    """Mean losses plus genre recall@10 on one loader pass."""
    model.eval()
    totals = {"music": 0.0, "genre": 0.0, "mood": 0.0, "energy": 0.0}
    hits = 0
    genre_total = 0
    with torch.no_grad():
        for batch in loader:
            outputs = model(batch["specs"])
            losses = model.loss(outputs, batch)
            for key in totals:
                totals[key] += losses.get(key, 0.0)
            top10 = outputs["genre"].topk(10, dim=-1).indices
            for i in range(top10.shape[0]):
                correct = {j for j in range(len(GENRE_VOCAB)) if batch["genre"][i, j] > 0}
                predicted = set(top10[i].tolist())
                hits += int(bool(correct & predicted))
            genre_total += batch["specs"].shape[0]
    n = max(genre_total, 1)
    return {key: value / n for key, value in totals.items()} | {"hits": hits / n}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the multi-task audio model")
    parser.add_argument("specs_dir", type=Path, help="preprocessed spectrogram .npy directory")
    parser.add_argument("--manifest", type=Path, required=True, help="manifest jsonl with labels")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--freeze-trunk", action="store_true", help="train heads only")
    parser.add_argument("--resume", action="store_true", help="continue from last.pt if present")
    parser.add_argument(
        "--keep-all", action="store_true", help="keep one checkpoint per epoch, not just last.pt"
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}")
    dataset = SpecDataset(args.manifest, args.specs_dir)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, collate_fn=collate)

    model = MultiTaskAST().to(device)
    if args.freeze_trunk:
        for param in model.encoder.parameters():
            param.requires_grad = False

    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr)
    start_epoch = 0
    # resume: rolling last.pt carries model plus optimizer state across runs
    if args.resume and (args.out_dir / "last.pt").exists():
        checkpoint = torch.load(args.out_dir / "last.pt", map_location=device)
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        start_epoch = checkpoint["epoch"] + 1
        print(f"resumed from epoch {checkpoint['epoch']}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.out_dir / "metrics.csv"
    if not metrics_path.exists() or start_epoch == 0:
        with metrics_path.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["epoch", "loss", "genre_recall@10"])
    with metrics_path.open("a", newline="") as metrics_file:
        writer = csv.writer(metrics_file)
        for epoch in range(start_epoch, args.epochs):
            model.train()
            running = 0.0
            batches = 0
            epoch_start = time.monotonic()
            for batch in loader:
                outputs = model(batch["specs"].to(next(model.parameters()).device))
                losses = model.loss(outputs, batch)
                loss = sum(losses.values())
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                running += loss.item()
                batches += 1
                # progress with ETA every 20 batches and on the last one
                if batches % 20 == 0 or batches == len(loader):
                    elapsed = time.monotonic() - epoch_start
                    eta = elapsed / batches * (len(loader) - batches)
                    print(
                        f"epoch {epoch}: batch {batches}/{len(loader)}, "
                        f"loss {running / batches:.4f}, eta {_format_duration(eta)}",
                        flush=True,
                    )
            eval_loss = evaluate(model, loader)
            writer.writerow([epoch, running / max(batches, 1), eval_loss["hits"]])
            # rolling checkpoint: model, optimizer, and epoch counter for resume
            torch.save(
                {"epoch": epoch, "model": model.state_dict(), "optimizer": optimizer.state_dict()},
                args.out_dir / "last.pt",
            )
            if args.keep_all:
                torch.save(model.state_dict(), args.out_dir / f"model_epoch{epoch}.pt")
            print(f"epoch {epoch}: eval genre recall@10 {eval_loss['hits']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
