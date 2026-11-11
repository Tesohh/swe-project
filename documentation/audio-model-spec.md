# Audio model output specification
The custom audio model reads one downloaded song and returns labels for the queue.
The list below is the contract the backend needs, and the dataset you must build for the next training run.

## Input contract
- The model reads the file that `download_song` writes, named `songs/<id>.mp3`
- The backend resamples audio to the sample rate that the checkpoint expects
- The model reads the first 5 minutes of a long track, so inference stays bounded
- The backend runs inference for each song and caches the result in the song row

## Output contract
```json
{
  "song_id": 42,
  "quality": "music",
  "genre": "reggaeton",
  "mood": "party",
  "energy": 0.82,
  "tempo_bpm": 96,
  "confidence": { "quality": 0.93, "genre": 0.88, "mood": 0.71 },
  "model_version": "audiemodel-v2",
  "analyzed_at": "2026-11-29T10:12:00Z"
}
```

The backend writes these values into the song row.

## Quality gate
The quality field decides whether the audio is music.
The model must return one class per song.

- music
- speech, for a podcast or a talk
- silent, for a video with empty audio
- broken, for silence, clipping, or a low-bitrate rip
- partial, for a clip with no intro or a trailer

The gate runs in the request path, before the app creates the queue entry.
A song that fails the gate keeps a song row with the class, and the response carries the reason.
The gate must reject a troll upload before the user votes.

## Admission rule
Not built yet. Nothing promotes a requested entry into the order today.
The quality gate decides admission, and the request path will run that gate.
A rejected song keeps its song row with the class, so the user can read the reason.
The reorder keeps a block term for a song that a host adds by hand.
Admission runs as an async job later: the request returns with the entry requested, and a worker
moves it to queued or drops it. The worker choice is open: BackgroundTasks, which loses a running
check when the backend restarts, or a song_checks table with a worker loop, which survives restarts.

## Genre vocabulary
The genre label must come from a closed list, so the reorder can penalize repeated genres.
The checkpoint ships a vocabulary file with a stable id for each label.

- pop
- rock
- metal
- punk
- hip hop
- rap
- phonk
- r and b
- soul
- funk
- reggaeton
- latin
- cumbia
- salsa
- electronic
- house
- techno
- trance
- drum and bass
- ambient
- jazz
- blues
- folk
- country
- classical
- kpop
- afrobeats

Add a genre to the list in a later training run, and keep the old ids unchanged.
An unrecognized label returns `unknown` instead of a guess.

## Mood vocabulary
The mood label must come from the same kind of closed list.
The queue matches mood against `Room.description`.

- party
- calm
- sad
- aggressive
- happy
- nostalgic
- romantic
- focus
- warm
- dark

## Energy
The model must return energy as a score from 0 to 1.
Energy covers loudness, density, and drive beyond genre and mood.
The reorder needs energy for a smooth ramp instead of a ballad after a club track.

## Tempo
The tempo field holds the BPM estimate.
The estimate must stay within 30 BPM for a track that a DJ mixes.
Silent or broken audio returns `null` tempo.

## Confidence and abstain
Each label carries a confidence score.
A low-confidence label must return `unknown`, so the host sees an unchecked song instead of a wrong genre.
The abstain threshold comes from the calibration run, and the backend keeps the threshold in config.

## Vector export, later run
Ask the checkpoint to export the penultimate layer as a vector.
The vector covers near-duplicate detection for different uploads of the same song, a case that `source_url` misses.
The vector also feeds the diversity pass that spreads similar songs apart.
The MVP runs without the vector, so ask for the vector in the next training run.

## Determinism
Same audio must produce the same labels.
The model must use no sampling step, so a song keeps one genre across rooms.
`model_version` records the checkpoint that produced the row.

## Failure paths
- If inference fails, keep `analyzed_at` empty and keep the request in `requested`
- If inference times out, retry 3 times and record the retry number in the song row
- The SSE stream tells the user that the song waits for the check
- The app creates a queue entry only after the quality gate returns music

## Dataset for the next training run
- The host correction table stores a wrong label that the host fixes, and that row becomes a training sample
- Keep each label with the `model_version` that produced the label, so dataset edits stay traceable
- Store every song that the quality gate rejected as a negative sample
- Store the votes and the played history for the ranker, and the audio model ignores those fields
- A genre list change needs a mapping table, so old rows keep their meaning after a vocabulary edit

## Checks after retraining
- genre: macro F1 per class, measured on the venue datasets that the app serves
- mood: balanced accuracy, because the classes carry unequal counts
- quality: recall of the music class, and precision of the reject classes
- energy: rank correlation against human annotations
- tempo: mean absolute error against the tap tempo of a human annotated track
- abstain rate: share of songs that return `unknown`
- latency per song on CPU, which must stay under 1 second

## Where the model runs
The AI server node in [concept-map.typ](documentation/concept-map.typ) holds the checkpoint.
The backend calls that node in the annotation job, and that job runs in a worker process.
A download must stay responsive while the model works on the file.
