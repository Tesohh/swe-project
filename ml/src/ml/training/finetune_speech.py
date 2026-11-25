"""Layer speech onto the trained music checkpoint: music/speech head only.

Loads runs/heads-only/last.pt, freezes trunk and other heads, then trains
just the music/speech head on speech positives plus balanced music negatives.
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
CHECKPOINT = Path("runs/heads-only/last.pt")
OUT_DIR = Path("runs/speech_head_ft")
SPEECH_MANIFEST = Path("data/manifests/speech.csv")
MUSIC_MANIFEST = Path("data/manifests/samples.jsonl")
NEG_PER_POS = 1  # music negatives per speech positive
EPOCHS = 40

random.seed(0)
OUT_DIR.mkdir(parents=True, exist_ok=True)

speech_rows = [
    {"id": row["id"], "genre": [], "mood": [], "audio_type": "speech"}
    for row in csv.DictReader(SPEECH_MANIFEST.open())
    if (SPECS_DIR / f"{row['id']}.npy").exists()
]
music_rows = [
    row
    for row in (json.loads(line) for line in MUSIC_MANIFEST.read_text().splitlines() if line.strip())
    if (SPECS_DIR / f"{row['id']}.npy").exists()
]
music_sample = random.sample(music_rows, min(NEG_PER_POS * len(speech_rows), len(music_rows)))
print(f"{len(speech_rows)} speech positives, {len(music_sample)} music negatives")


def make_set(rows: list[dict]) -> SpecDataset:
    dataset = SpecDataset.__new__(SpecDataset)
    dataset.specs_dir = SPECS_DIR
    dataset.rows = rows
    return dataset


loader = DataLoader(
    ConcatDataset([make_set(speech_rows), make_set(music_sample)]),
    batch_size=32,
    shuffle=True,
    collate_fn=collate,
)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = MultiTaskAST(n_genre=len(GENRE_VOCAB), n_mood=len(MOOD_VOCAB)).to(device)
checkpoint = torch.load(CHECKPOINT, map_location=device, weights_only=False)
model.load_state_dict(checkpoint["model"])
print(f"layered on checkpoint from epoch {checkpoint['epoch']}")

for param in model.encoder.parameters():
    param.requires_grad = False
for head in (model.genre_head, model.mood_head, model.energy_head):
    for param in head.parameters():
        param.requires_grad = False

optimizer = torch.optim.AdamW(model.music_head.parameters(), lr=5e-4)
# count each speech positive as much as a music negative so the head can leave the music prior
pos_weight = torch.tensor([sum(1 for r in speech_rows) / max(len(music_sample), 1)]).to(device)

for epoch in range(EPOCHS):
    model.train()
    running, batches, correct, seen = 0.0, 0, 0, 0
    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        outputs = model(batch["specs"])
        loss = F.binary_cross_entropy_with_logits(
            outputs["music"], batch["music_labels"].float(), pos_weight=pos_weight
        )
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        running += loss.item()
        batches += 1
        preds = (outputs["music"] > 0).float()
        correct += (preds == batch["music_labels"]).sum().item()
        seen += len(preds)
    print(f"epoch {epoch}: loss {running / max(batches, 1):.4f}, acc {correct / seen:.3f}", flush=True)

torch.save({"epoch": checkpoint["epoch"], "model": model.state_dict()}, OUT_DIR / "last.pt")
print(f"saved layered checkpoint to {OUT_DIR / 'last.pt'}")
