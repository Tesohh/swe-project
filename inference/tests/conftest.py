"""A tiny fake model, so the tests never download the real one from Hugging Face."""

import io

import numpy as np
import pytest
import soundfile
import torch
from fastapi.testclient import TestClient
from torch import nn

import src.main
from src.model_dep import get_model

GENRES = ["rock", "pop", "jazz", "metal"]
MOODS = ["happy", "sad", "calm"]
DIM = 8


class FakeModel(nn.Module):
    """Same outputs as MultiTaskAST, from a mean over the spectrogram."""

    def __init__(self):
        super().__init__()
        torch.manual_seed(0)
        self.genres = list(GENRES)
        self.moods = list(MOODS)
        self.proj = nn.Linear(128, DIM)
        self.music = nn.Linear(DIM, 1)
        self.genre = nn.Linear(DIM, len(GENRES))
        self.mood = nn.Linear(DIM, len(MOODS))
        self.energy = nn.Linear(DIM, 1)

    def forward(self, spec: torch.Tensor) -> dict[str, torch.Tensor]:
        embedding = self.proj(spec.mean(dim=1))
        return {
            "embedding": embedding,
            "music": self.music(embedding).squeeze(-1),
            "genre": self.genre(embedding),
            "mood": self.mood(embedding),
            "energy": torch.sigmoid(self.energy(embedding)).squeeze(-1),
        }


@pytest.fixture
def model() -> FakeModel:
    return FakeModel().eval()


@pytest.fixture
def client(model, monkeypatch):
    """App with the fake model. load_windows gives random features, because the real extractor comes from Hugging Face."""

    def fake_windows(audio: bytes, n_windows: int = 6) -> np.ndarray:
        assert isinstance(audio, bytes) and audio
        return np.random.default_rng(0).standard_normal((n_windows, 1024, 128)).astype(np.float16)

    monkeypatch.setattr(src.main, "load_windows", fake_windows)
    src.main.app.dependency_overrides[get_model] = lambda: model
    yield TestClient(src.main.app, raise_server_exceptions=False)
    src.main.app.dependency_overrides.clear()


def wav_bytes(seconds: float = 1.0, rate: int = 22050) -> bytes:
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    buffer = io.BytesIO()
    soundfile.write(buffer, 0.5 * np.sin(2 * np.pi * 440 * t), rate, format="WAV")
    return buffer.getvalue()
