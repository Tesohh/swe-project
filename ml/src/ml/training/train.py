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
import re
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


def sample_weights(rows: list[dict], power: float) -> list[float]:
    """Per-row sampling weight: seed boost times a rare-genre boost.

    power 0 keeps the old weights, 1 equalizes genre mass. Speech rows keep weight 1
    """
    base = [SEED_WEIGHT if row.get("origin") == "agent" else 1.0 for row in rows]
    if not power:
        return base
    mass: dict[str, float] = {}
    for row, weight in zip(rows, base):
        for genre in row.get("genre", []):
            mass[genre] = mass.get(genre, 0.0) + weight
    boost = [
        sum(mass[g] ** -power for g in row["genre"]) / len(row["genre"]) if row.get("genre") else None
        for row in rows
    ]
    mean = sum(b for b in boost if b is not None) / max(1, sum(b is not None for b in boost))
    # normalize so the music/speech ratio stays as before
    return [w if b is None else w * b / mean for w, b in zip(base, boost)]


def is_jamendo(row: dict) -> bool:
    """Dataset-tagged music rows (jamendo); seeds are agent-labelled, speech is not music."""
    return row.get("origin") == "dataset_tag" and row.get("audio_type", "music") == "music"


def assign_split(row: dict, held_out: set[tuple[str, str]], fold: int = 0, folds: int = 10) -> str:
    """test (held-out songs) / val (this fold's artists) / train. Folds partition artists."""
    if (normalize(row.get("artist", "")), normalize(row.get("title", ""))) in held_out:
        return "test"
    # rows without an artist (should not happen) fall into train rather than a shared bucket
    if row.get("artist") and fold / folds <= _artist_bucket(row["artist"]) < (fold + 1) / folds:
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
    """Rows joined with AST feature windows on disk.

    train: one item per track, a random window each call.
    eval:  one item per (track, window), so evaluation can average a track's windows
           the way inference does; items carry their track index in "_track".
    """

    def __init__(self, rows: list[dict], specs_dir: Path, train: bool):
        self.rows, self.specs_dir, self.train = rows, specs_dir, train
        self.items: list[tuple[int, int]] = []
        if not train:
            for i, row in enumerate(rows):
                n = len(np.load(specs_dir / f"{row['id']}.npy", mmap_mode="r"))
                self.items += [(i, w) for w in range(n)]

    def __len__(self) -> int:
        return len(self.rows) if self.train else len(self.items)

    def __getitem__(self, index: int) -> tuple[np.ndarray, dict]:
        if self.train:
            track = index
            windows = np.load(self.specs_dir / f"{self.rows[track]['id']}.npy", mmap_mode="r")
            pick = random.randrange(len(windows))
        else:
            track, pick = self.items[index]
            windows = np.load(self.specs_dir / f"{self.rows[track]['id']}.npy", mmap_mode="r")
        return np.array(windows[pick], dtype=np.float32), {**self.rows[track], "_track": track}


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
        "track": torch.tensor([row.get("_track", -1) for _, row in batch]),
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
    """Held-out metrics per track (windows averaged, as inference does).

    macro mAP per label head, genre top-1/top-3, music accuracy, energy MAE.
    """
    model.eval()
    parts: dict[str, list] = {
        k: []
        for k in (
            "genre",
            "mood",
            "music",
            "energy",
            "track",
            "genre_labels",
            "genre_mask",
            "mood_labels",
            "mood_mask",
            "music_labels",
            "energy_target",
            "energy_mask",
        )
    }
    with torch.no_grad(), torch.autocast(device.type, dtype=torch.bfloat16):
        for batch in loader:
            outputs = model(batch["specs"].to(device))
            for key in ("genre", "mood", "music"):
                parts[key].append(torch.sigmoid(outputs[key].float()).cpu())
            parts["energy"].append(outputs["energy"].float().cpu())
            parts["energy_target"].append(batch["energy"])
            for key in ("track", "genre_labels", "genre_mask", "mood_labels", "mood_mask"):
                parts[key].append(batch[key])
            parts["music_labels"].append(batch["music_labels"])
            parts["energy_mask"].append(batch["energy_mask"])
    cat = {k: torch.cat(v).numpy() for k, v in parts.items()}

    # average windows per track; labels are identical across a track's windows
    tracks, first, inverse = np.unique(cat["track"], return_index=True, return_inverse=True)

    def mean_by_track(values: np.ndarray) -> np.ndarray:
        sums = np.zeros((len(tracks),) + values.shape[1:], dtype=np.float64)
        np.add.at(sums, inverse, values)
        return sums / np.bincount(inverse).reshape((-1,) + (1,) * (values.ndim - 1))

    prob = {k: mean_by_track(cat[k]) for k in ("genre", "mood", "music", "energy")}
    tgt = {k: cat[k][first] for k in cat if k not in prob and k != "track"}
    labelled = tgt["genre_mask"][:, 0] > 0
    ranked = np.argsort(-prob["genre"][labelled], axis=1)
    true = tgt["genre_labels"][labelled]
    rows = np.arange(labelled.sum())
    energy_rows = tgt["energy_mask"] > 0
    return {
        "genre_map": _macro_ap(prob["genre"], tgt["genre_labels"], tgt["genre_mask"]),
        "genre_top1": float((true[rows, ranked[:, 0]] > 0).mean()) if labelled.any() else float("nan"),
        "genre_top3": float((true[rows[:, None], ranked[:, :3]] > 0).any(axis=1).mean())
        if labelled.any()
        else float("nan"),
        "mood_map": _macro_ap(prob["mood"], tgt["mood_labels"], tgt["mood_mask"]),
        "music_acc": float(((prob["music"] > 0.5) == (tgt["music_labels"] > 0.5)).mean()),
        "energy_mae": float(np.abs(prob["energy"] - tgt["energy_target"])[energy_rows].mean()),
    }


def spec_augment(specs: torch.Tensor, freq_mask: int = 24, time_mask: int = 96, masks: int = 2):
    """Zero random frequency bands and time spans (0 is the normalized mean level)."""
    specs = specs.clone()
    _, frames, bins = specs.shape
    for i in range(specs.shape[0]):
        for _ in range(masks):
            width = random.randint(0, freq_mask)
            start = random.randint(0, bins - width)
            specs[i, :, start : start + width] = 0
            width = random.randint(0, time_mask)
            start = random.randint(0, frames - width)
            specs[i, start : start + width, :] = 0
    return specs


def mixup(batch: dict[str, torch.Tensor], alpha: float = 0.4) -> dict[str, torch.Tensor]:
    """Blend each music row with another music row: audio and labels share one weight.

    Speech rows are left alone. A blended row keeps a head's loss only if both
    parents were labelled for that head.
    """
    n = batch["specs"].shape[0]
    perm = torch.randperm(n, device=batch["specs"].device)
    lam = float(torch.distributions.Beta(alpha, alpha).sample())
    ok = (batch["music_labels"] > 0.5) & (batch["music_labels"][perm] > 0.5)
    out = dict(batch)

    def blend(x: torch.Tensor, shape: tuple[int, ...]) -> torch.Tensor:
        return torch.where(ok.view(shape), lam * x + (1 - lam) * x[perm], x)

    out["specs"] = blend(batch["specs"], (-1, 1, 1))
    for head in ("genre", "mood"):
        out[f"{head}_labels"] = blend(batch[f"{head}_labels"], (-1, 1))
        mask = batch[f"{head}_mask"]
        out[f"{head}_mask"] = torch.where(ok.view(-1, 1), mask * mask[perm], mask)
    out["energy"] = blend(batch["energy"], (-1,))
    out["energy_mask"] = torch.where(ok, batch["energy_mask"] * batch["energy_mask"][perm], batch["energy_mask"])
    return out


def trunk_param_groups(encoder: torch.nn.Module, lr: float, decay: float) -> list[dict]:
    """Layer-wise learning-rate decay: the top layer gets lr, each layer below gets decay x less."""
    n_layers = len(encoder.layers)

    def depth(name: str) -> int:
        if name.startswith("embeddings"):
            return 0
        match = re.match(r"layers\.(\d+)\.", name)
        return int(match.group(1)) + 1 if match else n_layers + 1

    by_depth: dict[int, list[torch.nn.Parameter]] = {}
    for name, param in encoder.named_parameters():
        by_depth.setdefault(depth(name), []).append(param)
    return [
        {"params": params, "lr": lr * decay ** (n_layers + 1 - d)}
        for d, params in sorted(by_depth.items())
    ]


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
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--patience", type=int, default=3, help="stop after N epochs without gain")
    parser.add_argument("--fold", type=int, default=0, help="validation fold (artist-grouped)")
    parser.add_argument("--folds", type=int, default=10, help="number of artist-grouped folds")
    parser.add_argument("--lr-decay", type=float, default=0.85, help="per-layer trunk lr decay")
    parser.add_argument(
        "--specaug", action=argparse.BooleanOptionalAction, default=True, help="SpecAugment masks"
    )
    parser.add_argument("--balance", type=float, default=0.5, help="rare-genre sampling power, 0 off")
    parser.add_argument("--mixup-prob", type=float, default=0.5, help="chance a batch is mixed up")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--accum", type=int, default=4, help="gradient accumulation steps")
    parser.add_argument("--trunk-lr", type=float, default=3e-5)
    parser.add_argument("--head-lr", type=float, default=1e-3)
    parser.add_argument("--freeze-trunk", action="store_true", help="train heads only")
    parser.add_argument("--grad-checkpoint", action="store_true", help="trade speed for memory")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--drop-jamendo", action="store_true", help="exclude jamendo from training")
    parser.add_argument("--exclude-ids", type=Path, default=None, help="train ids to drop, one per line")
    parser.add_argument("--max-train", type=int, default=None, help="subsample train rows (smoke)")
    parser.add_argument("--max-val", type=int, default=None, help="subsample val rows (smoke)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}")

    held_out = test_keys()
    rows = load_rows(args.manifest, args.specs_dir)
    split: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for row in rows:
        split[assign_split(row, held_out, args.fold, args.folds)].append(row)
    if args.exclude_ids:
        dropped = set(args.exclude_ids.read_text().split())
        split["train"] = [r for r in split["train"] if r["id"] not in dropped]
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

    weights = sample_weights(split["train"], args.balance)
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
        groups += trunk_param_groups(model.encoder, args.trunk_lr, args.lr_decay)
    optimizer = torch.optim.AdamW(groups, weight_decay=0.01)
    total_steps = args.epochs * (len(train_loader) // args.accum)
    scheduler = make_scheduler(optimizer, total_steps)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.out_dir / "metrics.csv"
    columns = [
        "epoch",
        "train_loss",
        "genre_map",
        "genre_top1",
        "genre_top3",
        "mood_map",
        "music_acc",
        "energy_mae",
    ]
    with metrics_path.open("w", newline="") as file:
        csv.writer(file).writerow(columns)

    best, stale = -1.0, 0
    for epoch in range(args.epochs):
        model.train()
        running, batches, epoch_start = 0.0, 0, time.monotonic()
        optimizer.zero_grad()
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            if args.mixup_prob and random.random() < args.mixup_prob:
                batch = mixup(batch)
            if args.specaug:
                batch["specs"] = spec_augment(batch["specs"])
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
            best, stale = score, 0
            torch.save(checkpoint, args.out_dir / "best.pt")
        else:
            stale += 1
            if args.patience and stale >= args.patience:
                print(f"no gain for {stale} epochs; stopping")
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
