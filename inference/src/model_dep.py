import os
from functools import cache
from typing import Annotated

from fastapi import Depends

from src.inference import DEFAULT_REPO, DEFAULT_REVISION, load_from_hub
from src.model import MultiTaskAST


@cache
def get_model() -> MultiTaskAST:
    return load_from_hub(
        os.environ.get("MODEL_REPO", DEFAULT_REPO),
        os.environ.get("MODEL_REVISION", DEFAULT_REVISION),
    )


ModelDep = Annotated[MultiTaskAST, Depends(get_model)]
