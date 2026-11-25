"""Layer seed labels onto the checkpoint chain: genre/mood heads only.

Loads runs/speech_head_ft/last.pt (which already carries the jamendo heads-only
run plus the speech layer), freezes trunk and music/energy heads, then trains
genre_head and mood_head on seed rows plus a jamendo anchor sample.
"""

import csv
import json
import random
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import ConcatDataset, DataLoader

from ml.training.model import MultiTaskAST
from ml.training.train import GENRE_VOCAB, MOOD_VOCAB, SpecDataset, collate

SPECS_DIR = Path("data/specs")
CHECKPOINT = Path("runs/speech_head_ft/last.pt")
OUT_DIR = Path("runs/seed_head_ft")
SEED_MANIFEST = Path("data/manifests/seeds.csv")
MUSIC_MANIFEST = Path("data/manifests/samples.jsonl")
ANCHOR_ROWS = 500  # jamendo rows mixed in to protect the old learning
EPOCHS = 30
SEPARATOR = "|"

random.seed(0)
OUT_DIR.mkdir(parents=True, exist_ok=True)

seed_rows = [
    {"id": row["id"], "genre": row["genre"].split(SEPARATOR), "mood": row["mood"].split(SEPARATOR), "audio_type": "music"} for row in csv.DictReader(SEED_MANIFEST.open())
    if (SPECS_DIR / f"{row['id']}.npy").exists()
]
music_rows = [
    row
    for row in (json.loads(line) for line in MUSIC_MANIFEST.read_text().splitlines() if line.strip())
    if (SPECS_DIR / f"{row['id']}.npy").exists()
]
anchor_rows = random.sample(music_rows, min(ANCHOR_ROWS, len(music_rows)))
print(f"{len(seed_rows)} seed rows, {len(anchor_rows)} jamendo anchor rows")


def make_set(rows: list[dict]) -> SpecDataset:
    dataset = SpecDataset.__new__(SpecDataset)
    dataset.specs_dir = SPECS_DIR
    dataset.rows = rows
    return dataset


full_set = seed_rows + anchor_rows
loader = DataLoader(make_set(full_set), batch_size=32, shuffle=True, collate_fn=collate)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = MultiTaskAST(n_genre=len(GENRE_VOCAB), n_mood=len(MOOD_VOCAB)).to(device)
checkpoint = torch.load(CHECKPOINT, map_location=device, weights_only=False)
model.load_state_dict(checkpoint["model"])
print(f"loaded checkpoint chain up to epoch {checkpoint['epoch']}")

for param in model.encoder.parameters():
    param.requires_grad = False
for head in (model.music_head, model.energy_head):
    for param in head.parameters():
        param.requires_grad = False

optimizer = torch.optim.AdamW(
    [p for p in model.genre_head.parameters() if p.requires_grad]
    + [p for p in model.mood_head.parameters() if p.requires_grad],
    lr=5e-4,
)

for epoch in range(EPOCHS):
    model.train()
    running, batches = 0.0, 0
    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        outputs = model(batch["specs"])
        losses = {}
        # genre and mood losses reuse the masked BCE from the model definition
        losses["genre"] = model._masked_bce(
            outputs["genre"], batch["genre_labels"], batch["genre_mask"]
        )
        losses["mood"] = model._masked_bce(outputs["mood"], batch["mood_labels"], batch["mood_mask"])
        loss = sum(losses.values())
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        running += loss.item()
        batches += 1
    print(f"epoch {epoch}: loss {running / max(batches, 1):.4f}", flush=True)

torch.save({"epoch": checkpoint["epoch"], "model": model.state_dict()}, OUT_DIR / "last.pt")
print(f"saved layered checkpoint to {OUT_DIR / 'last.pt'}")
