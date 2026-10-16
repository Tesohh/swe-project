import logging
import os
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

engine = create_engine(os.environ["DATABASE_URL"])

log = logging.getLogger(__name__)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
