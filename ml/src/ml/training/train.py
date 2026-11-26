"""Joint training loop for the multi-task audio model.

One run from the pretrained AST: every source (jamendo, seeds, speech) lives in one
manifest, the trunk gets a low learning rate and the fresh heads a high one. Validation
is grouped by artist so a song's artist never sits on both sides of the split, and any
song in data/test_songs.jsonl is held out of training entirely.
"""

import argparse
import csv
import hashlib
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from ml.dataset.clean_seeds import normalize
from ml.dataset.vocabs import DATA_DIR, genre_list, mood_list
from ml.features import N_MELS, WINDOW_FRAMES
from ml.training.model import MultiTaskAST

# head indexes follow vocab-file order; checkpoints store the lists and inference checks them
GENRE_VOCAB = genre_list()
MOOD_VOCAB = mood_list()

VAL_FRACTION = 0.1
SEED_WEIGHT = 3.0  # hand-labelled seed songs are the target domain; sample them more often


def _artist_bucket(artist: str) -> float:
    """Stable [0, 1) hash of the normalized artist, so the split never reshuffles."""
    digest = hashlib.sha1(normalize(artist).encode()).hexdigest()
    return int(digest[:8], 16) / 0x100000000


def test_keys(path: Path = DATA_DIR / "test_songs.jsonl") -> set[tuple[str, str]]:
    """Normalized (artist, title) of the held-out smoke-test songs."""
    keys = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                artist, _, title = json.loads(line)["query"].partition(" - ")
                keys.add((normalize(artist), normalize(title)))
    return keys


def is_jamendo(row: dict) -> bool:
    """Dataset-tagged music rows (jamendo); seeds are agent-labelled, speech is not music."""
    return row.get("origin") == "dataset_tag" and row.get("audio_type", "music") == "music"


def assign_split(row: dict, held_out: set[tuple[str, str]]) -> str:
    if (normalize(row.get("artist", "")), normalize(row.get("title", ""))) in held_out:
        return "test"
    # rows without an artist (should not happen) fall into train rather than a shared bucket
    if row.get("artist") and _artist_bucket(row["artist"]) < VAL_FRACTION:
        return "val"
    return "train"


def load_rows(manifest_path: Path, specs_dir: Path) -> list[dict]:
    """Manifest rows joined with sidecar energy; only rows with a feature file survive."""
    energy = {}
    sidecar = specs_dir / "preprocessed.jsonl"
    if sidecar.exists():
        for line in sidecar.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                energy[record["id"]] = record["energy"]
    rows, seen = [], set()
    for line in manifest_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not row["id"] or row["id"] in seen or not (specs_dir / f"{row['id']}.npy").exists():
            continue
        seen.add(row["id"])
        row["energy"] = energy.get(row["id"])
        rows.append(row)
    return rows


class SpecDataset(Dataset):
    """Rows joined with AST feature windows on disk; train picks a random window per call."""

    def __init__(self, rows: list[dict], specs_dir: Path, train: bool):
        self.rows, self.specs_dir, self.train = rows, specs_dir, train

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[np.ndarray, dict]:
        windows = np.load(self.specs_dir / f"{self.rows[index]['id']}.npy", mmap_mode="r")
        pick = random.randrange(len(windows)) if self.train else len(windows) // 2
        return np.array(windows[pick], dtype=np.float32), self.rows[index]


def collate(batch, genre_vocab=GENRE_VOCAB, mood_vocab=MOOD_VOCAB) -> dict[str, torch.Tensor]:
    """Stack windows ([batch, 1024, 128]) and build label targets with per-head masks."""
    specs = torch.from_numpy(np.stack([spec for spec, _ in batch]))
    assert specs.shape[1:] == (WINDOW_FRAMES, N_MELS), specs.shape
    genre = torch.zeros(len(batch), len(genre_vocab))
    mood = torch.zeros(len(batch), len(mood_vocab))
    for i, (_, row) in enumerate(batch):
        for tag in row.get("genre", []):
            if tag in genre_vocab:
                genre[i, genre_vocab.index(tag)] = 1.0
        for tag in row.get("mood", []):
            if tag in mood_vocab:
                mood[i, mood_vocab.index(tag)] = 1.0
    energy = [row.get("energy") for _, row in batch]
    return {
        "specs": specs,
        "music_labels": torch.tensor(
            [1.0 if row.get("audio_type", "music") == "music" else 0.0 for _, row in batch]
        ),
        "genre_labels": genre,
        "genre_mask": (genre.sum(dim=1, keepdim=True) > 0).float(),
        "mood_labels": mood,
        "mood_mask": (mood.sum(dim=1, keepdim=True) > 0).float(),
        "energy": torch.tensor([e if e is not None else 0.0 for e in energy]),
        "energy_mask": torch.tensor([0.0 if e is None else 1.0 for e in energy]),
    }


def _format_duration(seconds: float) -> str:
    """ETA string like 12:34 or 1:02:03."""
    minutes, secs = divmod(int(seconds + 0.5), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _macro_ap(logits: np.ndarray, labels: np.ndarray, mask: np.ndarray) -> float:
    """Mean average precision over classes that have positives among labelled rows."""
    from sklearn.metrics import average_precision_score

    keep = mask[:, 0] > 0
    scores = []
    for j in range(labels.shape[1]):
        y = labels[keep, j]
        if 0 < y.sum() < len(y):
            scores.append(average_precision_score(y, logits[keep, j]))
    return float(np.mean(scores)) if scores else float("nan")


def evaluate(model: MultiTaskAST, loader: DataLoader, device: torch.device) -> dict[str, float]:
    """Held-out metrics: macro mAP per label head, top-1 genre, music accuracy, energy MAE."""
    model.eval()
    collected = {k: [] for k in ("genre", "mood", "music", "energy")}
    targets = {
        k: []
        for k in (
            "genre_labels",
            "genre_mask",
            "mood_labels",
            "mood_mask",
            "music_labels",
            "energy",
            "energy_mask",
        )
    }
    with torch.no_grad(), torch.autocast(device.type, dtype=torch.bfloat16):
        for batch in loader:
            outputs = model(batch["specs"].to(device))
            for key in collected:
                collected[key].append(outputs[key].float().cpu())
            for key in targets:
                targets[key].append(batch[key])
    out = {k: torch.cat(v).numpy() for k, v in collected.items()}
    tgt = {k: torch.cat(v).numpy() for k, v in targets.items()}
    labelled = tgt["genre_mask"][:, 0] > 0
    top1 = out["genre"][labelled].argmax(axis=1)
    hit = tgt["genre_labels"][labelled][np.arange(labelled.sum()), top1] > 0
    energy_rows = tgt["energy_mask"] > 0
    return {
        "genre_map": _macro_ap(out["genre"], tgt["genre_labels"], tgt["genre_mask"]),
        "genre_top1": float(hit.mean()) if labelled.any() else float("nan"),
        "mood_map": _macro_ap(out["mood"], tgt["mood_labels"], tgt["mood_mask"]),
        "music_acc": float(((out["music"] > 0) == (tgt["music_labels"] > 0.5)).mean()),
        "energy_mae": float(np.abs(out["energy"] - tgt["energy"])[energy_rows].mean()),
    }


def make_scheduler(optimizer, total_steps: int, warmup_fraction: float = 0.05):
    warmup = max(1, int(total_steps * warmup_fraction))

    def factor(step: int) -> float:
        if step < warmup:
            return (step + 1) / warmup
        progress = (step - warmup) / max(1, total_steps - warmup)
        return 0.5 * (1 + math.cos(math.pi * progress))

    return torch.optim.lr_scheduler.LambdaLR(optimizer, factor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the multi-task audio model")
    parser.add_argument("specs_dir", type=Path, help="AST feature .npy directory (ml.dataset.preprocess)")
    parser.add_argument("--manifest", type=Path, required=True, help="assembled samples jsonl")
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--accum", type=int, default=4, help="gradient accumulation steps")
    parser.add_argument("--trunk-lr", type=float, default=1e-5)
    parser.add_argument("--head-lr", type=float, default=1e-3)
    parser.add_argument("--freeze-trunk", action="store_true", help="train heads only")
    parser.add_argument("--grad-checkpoint", action="store_true", help="trade speed for memory")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--drop-jamendo", action="store_true", help="exclude jamendo from training")
    parser.add_argument("--max-train", type=int, default=None, help="subsample train rows (smoke)")
    parser.add_argument("--max-val", type=int, default=None, help="subsample val rows (smoke)")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    random.seed(0)
    torch.manual_seed(0)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}")

    held_out = test_keys()
    rows = load_rows(args.manifest, args.specs_dir)
    split: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for row in rows:
        split[assign_split(row, held_out)].append(row)
    if args.drop_jamendo:
        split["train"] = [r for r in split["train"] if not is_jamendo(r)]
    # validate on the target domain only (seed songs + speech), so runs with and
    # without jamendo are scored on identical rows
    split["val"] = [r for r in split["val"] if not is_jamendo(r)]
    if args.max_train:
        random.shuffle(split["train"])
        split["train"] = split["train"][: args.max_train]
    if args.max_val:
        random.shuffle(split["val"])
        split["val"] = split["val"][: args.max_val]
    print({name: len(items) for name, items in split.items()})
    if not split["train"] or not split["val"]:
        raise SystemExit("empty train or val split; is the specs dir populated?")

    weights = [SEED_WEIGHT if row.get("origin") == "agent" else 1.0 for row in split["train"]]
    train_loader = DataLoader(
        SpecDataset(split["train"], args.specs_dir, train=True),
        batch_size=args.batch_size,
        sampler=WeightedRandomSampler(weights, num_samples=len(weights), replacement=True),
        collate_fn=collate,
        num_workers=args.workers,
        persistent_workers=args.workers > 0,
        drop_last=True,
    )
    val_loader = DataLoader(
        SpecDataset(split["val"], args.specs_dir, train=False),
        batch_size=args.batch_size * 2,
        collate_fn=collate,
        num_workers=args.workers,
    )

    model = MultiTaskAST(n_genre=len(GENRE_VOCAB), n_mood=len(MOOD_VOCAB)).to(device)
    if args.grad_checkpoint:
        model.encoder.gradient_checkpointing_enable()
    heads = [model.music_head, model.genre_head, model.mood_head, model.energy_head]
    groups = [{"params": [p for h in heads for p in h.parameters()], "lr": args.head_lr}]
    if args.freeze_trunk:
        for param in model.encoder.parameters():
            param.requires_grad = False
    else:
        groups.append({"params": list(model.encoder.parameters()), "lr": args.trunk_lr})
    optimizer = torch.optim.AdamW(groups, weight_decay=0.01)
    total_steps = args.epochs * (len(train_loader) // args.accum)
    scheduler = make_scheduler(optimizer, total_steps)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.out_dir / "metrics.csv"
    columns = ["epoch", "train_loss", "genre_map", "genre_top1", "mood_map", "music_acc", "energy_mae"]
    with metrics_path.open("w", newline="") as file:
        csv.writer(file).writerow(columns)

    best = -1.0
    for epoch in range(args.epochs):
        model.train()
        running, batches, epoch_start = 0.0, 0, time.monotonic()
        optimizer.zero_grad()
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            with torch.autocast(device.type, dtype=torch.bfloat16):
                outputs = model(batch["specs"])
            losses = model.loss(outputs, batch)
            loss = sum(losses.values())
            (loss / args.accum).backward()
            batches += 1
            running += loss.item()
            if batches % args.accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
            # progress with ETA every 20 batches and on the last one
            if batches % 20 == 0 or batches == len(train_loader):
                eta = (time.monotonic() - epoch_start) / batches * (len(train_loader) - batches)
                print(
                    f"epoch {epoch}: batch {batches}/{len(train_loader)}, "
                    f"loss {running / batches:.4f}, eta {_format_duration(eta)}",
                    flush=True,
                )
        metrics = evaluate(model, val_loader, device)
        with metrics_path.open("a", newline="") as file:
            csv.writer(file).writerow(
                [epoch, running / max(batches, 1)] + [metrics[c] for c in columns[2:]]
            )
        print(f"epoch {epoch}: val " + ", ".join(f"{k} {v:.3f}" for k, v in metrics.items()))
        # best-checkpoint criterion: mean of the two label-head mAPs (nan-safe)
        score = float(np.nanmean([metrics["genre_map"], metrics["mood_map"]]))
        checkpoint = {
            "epoch": epoch,
            "model": model.state_dict(),
            "genres": GENRE_VOCAB,
            "moods": MOOD_VOCAB,
            "metrics": metrics,
        }
        torch.save(checkpoint, args.out_dir / "last.pt")
        if score > best:
            best = score
            torch.save(checkpoint, args.out_dir / "best.pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
