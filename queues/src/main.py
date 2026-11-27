import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

import src.db
import src.internal
import src.models
import src.queue.host_router
import src.queue.user_router
import src.room.router

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
    title="queues",
    root_path="/api",
    lifespan=lifespan,
    docs_url="/room/docs",
    openapi_url="/room/openapi.json",
)
app.state.is_dev = os.getenv("DEPLOYMENT_ENV") == "development"

app.include_router(src.room.router.router, tags=["room"])
app.include_router(src.queue.host_router.router, tags=["queue-host"])
app.include_router(src.queue.user_router.router, tags=["queue"])
app.include_router(src.internal.router, tags=["internal"])
