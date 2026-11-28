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
| Easy test set | 87 | 76% (66/87) | 91% (79/87) |
| Hard test set (borderline and non-English songs) | 152 | 69% (105/152) | 89% (136/152) |

Validation (531 tracks, grouped by artist or by sound source): genre mAP 0.689, mood mAP 0.506,
music-or-not accuracy 98.9%, energy MAE 0.035.

Top-1 means the highest-scoring genre equals the expected genre. A song often has more than one
valid genre, so top-3 is the fairer number.

### Music-or-not head

The `music` output is a score from 0 to 1. It was tested on 83 clips and 5 videos that are not in the
training data. Each clip is 60 seconds from YouTube. The table shows the mean `p_music` per group.

| Group | Clips | Mean p_music |
|---|---|---|
| Rain, ocean, birds, traffic | 12 | 0.03 |
| Crowd, bar and street noise | 12 | 0.09 |
| Applause | 3 | 0.07 |
| Sound effects | 4 | 0.21 |
| Podcast and talk | 11 | 0.25 |
| Folk, a cappella, solo instruments | 10 | 1.00 |
| Non-English speech | 12 | 0.52 |
| Ringtones, jingles, modem sounds | 7 | 0.75 |
| Music with speech over it | 7 | 0.64 |

Speech and noise that have no music get a low score. Music gets a high score.
Non-English speech and music with speech over it are not reliable. The test clips were not checked by
listening. Some of them may contain music.

### Known weak spots

- The music-or-not score is not reliable for non-English speech, for speech over music, and for ringtones.
- A short sound effect (for example a vacuum cleaner) can still get a high music score.

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
- Data: about 17,400 tracks. About 12,000 come from MTG-Jamendo, with genre tags mapped to the
  21 genres. About 3,900 are well-known songs that were labeled by hand and with model help (genre and mood).
  About 275 are speech clips and about 1,300 are noise clips (for the music-or-not head).
  The noise clips are environmental sounds (ESC-50, 4 or more clips joined to at least 12 seconds),
  synthetic sounds (silence, noise, tones) and YouTube ambience and sound effects. The speech clips
  are LibriVox audiobooks and YouTube talk and news. Windows that contain music are removed from the
  noise and speech clips (AudioSet Music score of 0.2 or more).
- Songs and artists in the test sets are excluded from training. The validation split is grouped by artist.
- Up to 12 epochs with early stopping (the saved model is from epoch 5), AdamW, trunk learning rate 3e-5
  with layer decay 0.85, head learning rate 1e-3, effective batch 32, bf16.
  One random 10.24 second window per track in each step. About 55 minutes on one consumer GPU (RTX 3080).

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
