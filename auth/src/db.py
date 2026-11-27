import logging
import os
import time
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine

engine = create_engine(os.environ["DATABASE_URL"])

log = logging.getLogger(__name__)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def create_db_and_tables(attempts: int = 30):
    # postgres may still start when the service starts, so retry
    for attempt in range(1, attempts + 1):
        try:
            SQLModel.metadata.create_all(engine)
            return
        except OperationalError:
            if attempt == attempts:
                raise
            log.info("postgres is not ready, try %s of %s", attempt, attempts)
            time.sleep(1)
