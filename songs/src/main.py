import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

import src.db
import src.models
import src.router

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    src.db.create_db_and_tables()
    log.info("created db and tables")
    yield


app = FastAPI(
    title="songs",
    root_path="/api",
    lifespan=lifespan,
    docs_url="/song/docs",
    openapi_url="/song/openapi.json",
)
app.state.is_dev = os.getenv("DEPLOYMENT_ENV") == "development"

app.include_router(src.router.router, tags=["song"])
app.include_router(src.router.internal, tags=["internal"])
