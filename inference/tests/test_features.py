import os

import numpy as np
import pytest

from src.features import SAMPLE_RATE, WINDOW_SAMPLES, audio_to_windows, load_audio, window_starts
from src.inference import score_windows
from tests.conftest import DIM, GENRES, MOODS, wav_bytes


def test_window_starts_short_audio_is_one_window():
    assert window_starts(WINDOW_SAMPLES // 2, 6) == [0]


def test_window_starts_one_window_is_centered():
    assert window_starts(WINDOW_SAMPLES + 100, 1) == [50]


def test_window_starts_skip_edges_and_stay_in_bounds():
    n = WINDOW_SAMPLES * 10
    starts = window_starts(n, 6)
    spare = n - WINDOW_SAMPLES
    assert len(starts) == 6
    assert starts == sorted(starts)
    assert starts[0] == int(spare * 0.15)
    assert starts[-1] == int(spare * 0.85)
    assert all(0 <= s and s + WINDOW_SAMPLES <= n for s in starts)


def test_load_audio_resamples_to_mono_16k():
    audio = load_audio(wav_bytes(seconds=1.0, rate=22050))
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert abs(len(audio) - SAMPLE_RATE) <= 1


def test_load_audio_caps_length():
    audio = load_audio(wav_bytes(seconds=2.0), max_seconds=1.0)
    assert len(audio) <= SAMPLE_RATE + 1


def test_score_windows(model):
    windows = np.random.default_rng(1).standard_normal((3, 1024, 128)).astype(np.float16)
    scores = score_windows(model, windows)
    assert scores["windows"] == 3
    assert set(scores["genre"]) == set(GENRES)
    assert set(scores["mood"]) == set(MOODS)
    assert 0 <= scores["p_music"] <= 1
    assert scores["embedding"].shape == (DIM,)
    assert np.isclose(np.linalg.norm(scores["embedding"]), 1.0, atol=1e-3)


@pytest.mark.skipif(not os.environ.get("RUN_HF_TESTS"), reason="downloads the AST feature extractor; set RUN_HF_TESTS=1")
def test_audio_to_windows_shape():
    windows = audio_to_windows(load_audio(wav_bytes(seconds=3.0)), 4)
    assert windows.dtype == np.float16
    assert windows.shape == (1, 1024, 128)  # shorter than one window, so one window
