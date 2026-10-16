import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import src.auth
import src.auth.router
import src.db
import src.models
import src.ws.router

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # stuff that is run at startup
    src.db.create_db_and_tables()
    log.info("created db and tables")
    # add more here if needed ...
    log.info("done all startup procedures")

    yield

    # stuff that is run at shutdown
    # add more here if needed ...


app = FastAPI(title="GIVE ME A NAME", root_path="/api", lifespan=lifespan)
app.state.is_dev = os.getenv("DEPLOYMENT_ENV") == "development"

app.include_router(src.auth.router.router, tags=["auth"])
app.include_router(src.ws.router.router, tags=["ws"])

app.mount("/static", StaticFiles(directory=Path.cwd() / "static"), name="assets")
