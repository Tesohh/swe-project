from typing import Annotated

from common.auth import CurrentUserDep, verify_password
from fastapi import Depends, HTTPException, status
from sqlmodel import Session, select

import src.db
import src.models


def authenticate_user(session: Session, username: str, password: str) -> src.models.User | None:
    user = session.exec(select(src.models.User).where(src.models.User.name == username)).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(session: src.db.SessionDep, current: CurrentUserDep) -> src.models.User:
    """The users row of the caller. A token of a deleted user is refused."""
    user = session.get(src.models.User, current.id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


UserDep = Annotated[src.models.User, Depends(get_current_user)]
