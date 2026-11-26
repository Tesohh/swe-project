---
license: cc-by-nc-sa-4.0
library_name: pytorch
pipeline_tag: audio-classification
base_model: MIT/ast-finetuned-audioset-10-10-0.4593
tags:
  - audio
  - music
  - genre-classification
  - mood
  - embeddings
  - audio-spectrogram-transformer
---

# music-tagger-ast

Music tagger for a university project (a shared music queue app).
It takes a song and returns genre tags, mood tags, an energy value, a music-or-not score, and an embedding for similar-song search.

The model is the Audio Spectrogram Transformer (AST) from `MIT/ast-finetuned-audioset-10-10-0.4593`,
fine-tuned with four output heads on a shared trunk. It has 86.2 million parameters.

## Outputs

| Output | Type | Size |
|---|---|---|
| `music` | music or not (speech, noise) | 1 value |
| `genre` | multi-label | 21 genres |
| `mood` | multi-label | 11 moods |
| `energy` | regression, 0 to 1 | 1 value |
| `embedding` | pooled trunk vector | 768 values |

Genres: `rock`, `pop`, `rap`, `jazz`, `blues`, `electronic`, `techno`, `house`, `ambient`, `folk`, `country`,
`reggae`, `funk`, `soul`, `rnb`, `metal`, `punk`, `classical`, `latin`, `world`, `experimental`.
Techno and house songs also carry `electronic`.

Moods: `calm`, `sad`, `happy`, `party`, `energetic`, `dark`, `romantic`, `aggressive`, `dreamy`, `melancholic`, `dramatic`.

## Results

All numbers are for songs by artists that are not in the training data.

| Test | Songs | Top-1 genre | Top-3 genre |
|---|---|---|---|
| Easy test set | 87 | 70% (61/87) | 93% (81/87) |
| Hard test set (borderline and non-English songs) | 152 | 68% (103/152) | 90% (137/152) |

Validation (434 tracks, artist-grouped): genre mAP 0.683, mood mAP 0.523, music-or-not accuracy 99.8%,
energy MAE 0.03.

Top-1 means the highest-scoring genre equals the expected genre. A song often has more than one
valid genre, so top-3 is the fairer number.

### Known weak spots

- Many songs get `rock`, `pop` or `electronic` when they are not.
- `house` is weak. It is often called `electronic`.
- `world`, `punk`, `rnb` and `country` are weak. `rnb` is often called `pop`.
- The mood head is the weakest head. Mood labels are subjective.
- The energy value is a loudness measure, not a human rating.
- Few `ambient`, `techno` and `experimental` songs are in the test sets, so these results are uncertain.

## How to use

The model class and the feature code are in the project repository:
https://github.com/Tesohh/swe-project (folder `ml/`).

```python
from huggingface_hub import snapshot_download
from ml.inference import load_model, load_windows, score_windows

path = snapshot_download("tesohh/music-tagger-ast")
model = load_model(f"{path}/model.safetensors")
scores = score_windows(model, load_windows("song.mp3"))
print(scores["genre"], scores["mood"], scores["energy"], scores["p_music"])
```

Input: 16 kHz mono audio. The code takes 6 windows of 10.24 seconds from the song body, scores each
one, and averages them. Features are 128-bin log-mel filterbanks with the AST normalization.
The `embedding` is a unit vector. The dot product of two embeddings is their cosine similarity.

## Training

- Start: `MIT/ast-finetuned-audioset-10-10-0.4593` (AudioSet).
- Data: about 16,000 tracks. About 12,000 come from MTG-Jamendo, with genre tags mapped to the
  21 genres. About 3,900 are well-known songs that were labeled by hand and with model help (genre and mood).
  About 150 are speech clips (for the music-or-not head).
- Songs and artists in the test sets are excluded from training. The validation split is grouped by artist.
- 6 epochs, AdamW, trunk learning rate 1e-5, head learning rate 1e-3, effective batch 32, bf16.
  One random 10.24 second window per track in each step. About 40 minutes on one consumer GPU (RTX 3080).

The training audio is not included in this repository. Only the model weights are.

## Limits and intended use

This is a university project model. Use it for tagging and for rough similarity search.
Do not use it for decisions that matter. Labels for the hand-labeled songs come from the
authors and a language model, and they reflect Western popular music more than other music.

## License

The weights are shared under CC BY-NC-SA 4.0 (non-commercial). Reasons: part of the training data is
from MTG-Jamendo (non-commercial research terms), and the base model is AST (BSD-3-Clause, attribution required).

## Credits

- AST: Gong, Chung, Glass. "AST: Audio Spectrogram Transformer", Interspeech 2021.
- MTG-Jamendo dataset: Bogdanov et al., 2019.
