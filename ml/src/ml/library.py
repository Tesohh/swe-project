"""Library embeddings and similar-song search.

build:   embed every track that has AST feature windows, save ids + unit vectors + labels.
similar: nearest tracks to a library song ("Artist - Title") or to an audio file.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from ml.dataset.clean_seeds import normalize
from ml.inference import DEFAULT_CHECKPOINT, load_model, load_windows, score_windows

DEFAULT_LIBRARY = Path("runs/rap_a/library.npz")
DEFAULT_MANIFEST = Path("data/manifests/train.jsonl")
DEFAULT_SPECS = Path("data/specs_ast")


def build(checkpoint: Path, manifest: Path, specs_dir: Path, out: Path, batch_tracks: int = 32):
    """Embed all manifest rows with features; windows are averaged per track, unit length."""
    model = load_model(checkpoint)
    device = next(model.parameters()).device
    rows = [json.loads(l) for l in manifest.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["id"] and (specs_dir / f"{r['id']}.npy").exists()]
    vectors = []
    for start in range(0, len(rows), batch_tracks):
        chunk = rows[start : start + batch_tracks]
        windows = [np.load(specs_dir / f"{r['id']}.npy") for r in chunk]
        counts = [len(w) for w in windows]
        batch = torch.from_numpy(np.concatenate(windows).astype(np.float32)).to(device)
        with torch.no_grad(), torch.autocast(device.type, dtype=torch.bfloat16):
            emb = model(batch)["embedding"].float()
        emb = torch.nn.functional.normalize(emb, dim=-1)
        for part in torch.split(emb, counts):
            vectors.append(torch.nn.functional.normalize(part.mean(dim=0), dim=-1).cpu().numpy())
        if (start // batch_tracks) % 50 == 0:
            print(f"embedded {start + len(chunk)}/{len(rows)}", flush=True)
    meta = [
        {k: r.get(k) for k in ("id", "artist", "title", "genre", "mood", "audio_type", "origin")}
        for r in rows
    ]
    np.savez(out, vectors=np.stack(vectors), meta=json.dumps(meta))
    print(f"saved {len(rows)} track vectors to {out}")


def load_library(path: Path) -> tuple[np.ndarray, list[dict]]:
    data = np.load(path, allow_pickle=False)
    return data["vectors"], json.loads(str(data["meta"]))


def find_track(meta: list[dict], query: str) -> int:
    """Index of the library track whose 'artist - title' matches the query best."""
    want = normalize(query)
    scored = [
        (i, normalize(f"{m['artist']} {m['title']}"))
        for i, m in enumerate(meta)
        if m["audio_type"] == "music"
    ]
    exact = [i for i, key in scored if key == want]
    if exact:
        return exact[0]
    contains = [i for i, key in scored if want in key]
    if not contains:
        raise SystemExit(f"no library track matches {query!r}")
    return contains[0]


def search(vector: np.ndarray, vectors: np.ndarray, meta: list[dict], k: int, skip: int | None):
    sims = vectors @ vector
    if skip is not None:
        sims[skip] = -1
    for i, m in enumerate(meta):  # speech is never a "similar song"
        if m["audio_type"] != "music":
            sims[i] = -1
    top = np.argsort(-sims)[:k]
    return [(float(sims[i]), meta[i]) for i in top]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Library embeddings and similar songs")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="embed the whole library")
    b.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    b.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    b.add_argument("--specs-dir", type=Path, default=DEFAULT_SPECS)
    b.add_argument("--out", type=Path, default=DEFAULT_LIBRARY)
    s = sub.add_parser("similar", help="nearest library songs")
    s.add_argument("query", nargs="+", help="'Artist - Title' in the library, or an audio file path")
    s.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    s.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    s.add_argument("-k", type=int, default=8)
    args = parser.parse_args(argv)

    if args.command == "build":
        build(args.checkpoint, args.manifest, args.specs_dir, args.out)
        return 0

    vectors, meta = load_library(args.library)
    model = None
    for query in args.query:
        skip = None
        if Path(query).exists():
            model = model or load_model(args.checkpoint)
            vector = score_windows(model, load_windows(Path(query)))["embedding"]
            label = Path(query).name
        else:
            skip = find_track(meta, query)
            vector, label = vectors[skip], f"{meta[skip]['artist']} - {meta[skip]['title']}"
        print(f"\n== similar to {label}")
        for sim, m in search(vector, vectors, meta, args.k, skip):
            tags = "|".join(m["genre"] or [])
            print(f"  {sim:.3f}  {m['artist'][:28]} - {m['title'][:40]}  [{tags}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
