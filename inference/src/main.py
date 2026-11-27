from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.model_dep import ModelDep, get_model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # load the model once at startup, so the first request is not slow
    get_model()
    yield


app = FastAPI(title="tagger", root_path="/inference", lifespan=lifespan)


@app.get("/health")
def health(model: ModelDep):
    return {"loaded": True, "device": next(model.parameters()).device.type}


@app.post("/analyze")
def analyze(_model: ModelDep):
    # TODO: accept an audio upload, call score_windows(model, ...), return the scores
    raise NotImplementedError
