from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src.inference import Scores, load_windows, score_windows
from src.model_dep import ModelDep, get_model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # load the model once at startup, so the first request is not slow
    get_model()
    yield


app = FastAPI(title="tagger", root_path="/inference", lifespan=lifespan)


class HealthResult(BaseModel):
    loaded: bool  # the model is loaded
    device: str  # device of the model, e.g. "cpu" or "cuda"


class ErrorDetail(BaseModel):
    detail: str


@app.get("/health")
def health(model: ModelDep) -> HealthResult:
    """Tells that the model is loaded, and on which device it runs."""
    return HealthResult(loaded=True, device=next(model.parameters()).device.type)


ALLOWED_MIME_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/ogg",
    "application/ogg",
    "audio/mpeg",
    "audio/aiff",
    "audio/webm",
    "video/webm",
    "audio/mp4",
}


def get_top_k(scores: dict[str, float], k: int) -> dict[str, float]:
    k = int(k)
    return dict(sorted(scores.items(), key=lambda x: -x[1])[:k])


class AnalyzeResult(BaseModel):
    p_music: float  # 0..1, probability that the audio is music
    genre: dict[str, float]  # genre name -> 0..1 probability
    mood: dict[str, float]  # mood name -> 0..1 probability
    energy: float
    windows: int  # number of windows the scores are averaged over
    embedding: list[float]  # float32 [dim], unit length

    @staticmethod
    def from_scores(scores: Scores, top_k=3) -> AnalyzeResult:
        return AnalyzeResult(
            p_music=scores["p_music"],
            genre=get_top_k(scores["genre"], top_k),
            mood=get_top_k(scores["mood"], top_k),
            energy=scores["energy"],
            windows=scores["windows"],
            embedding=scores["embedding"].tolist(),
        )


@app.post("/analyze", responses={415: {"model": ErrorDetail, "description": "The audio type is not supported"}})
def analyze(model: ModelDep, file: UploadFile, top_k: int = Query(default=3, ge=1)) -> AnalyzeResult:
    """Tags the audio file: music probability, the top_k genres and moods, energy, and an embedding."""
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"unsupported audio type: {file.content_type}")
    scores = score_windows(model, load_windows(file.file.read()))
    return AnalyzeResult.from_scores(scores, top_k)
