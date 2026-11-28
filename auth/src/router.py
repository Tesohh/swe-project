from typing import Annotated

from common.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash,
    oauth2_scheme,
    verify_password,
)
from common.http import base_url, call
from common.schemas import Status, errors
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlmodel import col, delete, select, update

import src.db
import src.models
import src.security

router = APIRouter(prefix="/auth")

# routes for the other services. The gateway does not route /internal, so the browser cannot reach them
internal = APIRouter(prefix="/internal")


class SignupBody(BaseModel):
    username: str
    password: str


@router.post("/token", responses=errors(401))
def get_oauth2_token(
    session: src.db.SessionDep,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Status:
    """Checks the username and password. On success, sets the JWT cookie (httpOnly) and returns the status."""
    user = src.security.authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": str(user.id)})
    response.set_cookie(
        oauth2_scheme.token_name,
        access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=True,
        samesite="lax",
        path="/api",
    )
    return Status(status="authenticated")


@router.post("/signup", responses=errors(409))
def signup(session: src.db.SessionDep, body: SignupBody) -> src.models.User:
    """Creates a user. The name must be new."""
    user = session.exec(select(src.models.User).where(src.models.User.name == body.username)).first()
    if user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already registered")

    user = src.models.User(name=body.username, password_hash=get_password_hash(body.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/me", responses=errors(401))
def me(user: src.security.UserDep) -> src.models.User:
    """The user of the JWT cookie."""
    return user


@router.post("/logout")
def logout(response: Response) -> Status:
    """Deletes the JWT cookie."""
    response.delete_cookie(oauth2_scheme.token_name, httponly=True, secure=True, samesite="lax", path="/api")
    return Status(status="cookie deleted")


@router.post("/delete", responses=errors(401, 502))
def delete_account(user: src.security.UserDep, session: src.db.SessionDep) -> Status:
    """Deletes the account of the user, and the rooms and votes of the user in the queues service."""
    # the queues service holds the rooms and votes of the user. It goes first, so a failure keeps the account
    call("queues", "DELETE", f"{base_url('QUEUES_BASE', 'http://queues:8000')}/internal/users/{user.id}")

    session.exec(delete(src.models.User).where(src.models.User.id == user.id))  # type:ignore
    session.commit()
    return Status()


class ChangeUsernameBody(BaseModel):
    new_username: str


@router.post("/change_username", responses=errors(401, 409))
def change_username(session: src.db.SessionDep, user: src.security.UserDep, body: ChangeUsernameBody) -> Status:
    """Changes the name of the user. The new name must be new."""
    db_user = session.exec(select(src.models.User).where(src.models.User.name == body.new_username)).first()
    if db_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already registered")

    user.name = body.new_username

    session.exec(update(src.models.User).where(src.models.User.id == user.id).values(name=body.new_username))  # type:ignore
    session.commit()
    return Status()


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


@router.post("/change_password", responses=errors(401))
def change_password(session: src.db.SessionDep, user: src.security.UserDep, body: ChangePasswordBody) -> Status:
    """Changes the password of the user. old_password must be correct."""
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    new_password_hash = get_password_hash(body.new_password)

    user.password_hash = new_password_hash

    session.exec(update(src.models.User).where(src.models.User.id == user.id).values(password_hash=new_password_hash))  # type:ignore
    session.commit()
    return Status()


@internal.get("/users/names")
def user_names(session: src.db.SessionDep, ids: Annotated[list[int] | None, Query()] = None) -> dict[int, str]:
    """User id to name, for the ids that exist."""
    if not ids:
        return {}
    rows = session.exec(select(src.models.User).where(col(src.models.User.id).in_(ids))).all()
    return {row.id: row.name for row in rows if row.id is not None}
