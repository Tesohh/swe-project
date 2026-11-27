from functools import cache

import numpy as np

BACKBONE = "MIT/ast-finetuned-audioset-10-10-0.4593"
SAMPLE_RATE = 16000
N_MELS = 128
WINDOW_FRAMES = 1024
# 1024 frames at a 10 ms hop is 10.24 s of audio
WINDOW_SAMPLES = SAMPLE_RATE * WINDOW_FRAMES // 100
# window placement ignores the first/last slice of a track (intros, fades)
EDGE_FRACTION = 0.15
# cap decoded audio so one 50-minute audiobook does not dominate preprocessing
MAX_AUDIO_SECONDS = 600


@cache
def extractor():
    from transformers import ASTFeatureExtractor

    fe = ASTFeatureExtractor.from_pretrained(BACKBONE)
    assert (fe.sampling_rate, fe.num_mel_bins, fe.max_length) == (
        SAMPLE_RATE,
        N_MELS,
        WINDOW_FRAMES,
    ), "AST feature extractor config changed; update src.features constants"
    return fe


def load_audio(source, max_seconds: float = MAX_AUDIO_SECONDS) -> np.ndarray:
    """Mono float32 samples at the AST sample rate; ffmpeg decodes what libsndfile cannot."""
    import io

    import librosa

    try:
        target = io.BytesIO(source) if isinstance(source, bytes) else str(source)
        audio, _ = librosa.load(target, sr=SAMPLE_RATE, mono=True, duration=max_seconds)
        return audio
    except Exception:  # noqa: BLE001 - webm/opus and mislabelled containers land here
        return _load_with_ffmpeg(source, max_seconds)


def _load_with_ffmpeg(source, max_seconds: float) -> np.ndarray:
    import subprocess

    is_bytes = isinstance(source, bytes)
    command = [
        "ffmpeg", "-v", "error", "-i", "pipe:0" if is_bytes else str(source), "-t", str(max_seconds),
        "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-",
    ]  # fmt: skip
    result = subprocess.run(command, input=source if is_bytes else None, capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype=np.float32)


def window_starts(n_samples: int, n_windows: int) -> list[int]:
    """Evenly spaced window starts, inside the track body when it is long enough."""
    spare = n_samples - WINDOW_SAMPLES
    if spare <= 0 or n_windows <= 1:
        return [max(spare // 2, 0)]
    lo, hi = int(spare * EDGE_FRACTION), int(spare * (1 - EDGE_FRACTION))
    return [int(s) for s in np.linspace(lo, hi, n_windows)]


def audio_to_windows(audio: np.ndarray, n_windows: int) -> np.ndarray:
    """Waveform -> float16 [n_windows, 1024, 128], normalized the way AST expects."""
    starts = window_starts(len(audio), n_windows)
    chunks = [audio[s : s + WINDOW_SAMPLES] for s in starts]
    features = extractor()(chunks, sampling_rate=SAMPLE_RATE, return_tensors="np")
    return features["input_values"].astype(np.float16)
