from typing import Annotated

from common.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash,
    oauth2_scheme,
    verify_password,
)
from common.http import base_url, call
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
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


@router.post("/token")
def get_oauth2_token(
    session: src.db.SessionDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    user = src.security.authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": str(user.id)})
    response = JSONResponse({"status": "authenticated"})
    response.set_cookie(
        oauth2_scheme.token_name,
        access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=True,
        samesite="lax",
        path="/api",
    )
    return response


@router.post("/signup")
def signup(session: src.db.SessionDep, body: SignupBody) -> src.models.User:
    user = session.exec(select(src.models.User).where(src.models.User.name == body.username)).first()
    if user:
        raise HTTPException(status_code=408, detail="Username already registered")

    user = src.models.User(name=body.username, password_hash=get_password_hash(body.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/me")
def me(user: src.security.UserDep) -> src.models.User:
    return user


@router.post("/logout")
def logout():
    response = JSONResponse({"status": "cookie deleted"})
    response.delete_cookie(oauth2_scheme.token_name, httponly=True, secure=True, samesite="lax", path="/api")
    return response


@router.post("/delete")
def delete_account(user: src.security.UserDep, session: src.db.SessionDep):
    # the queues service holds the rooms and votes of the user. It goes first, so a failure keeps the account
    call("queues", "DELETE", f"{base_url('QUEUES_BASE', 'http://queues:8000')}/internal/users/{user.id}")

    session.exec(delete(src.models.User).where(src.models.User.id == user.id))  # type:ignore
    session.commit()


class ChangeUsernameBody(BaseModel):
    new_username: str


@router.post("/change_username")
def change_username(session: src.db.SessionDep, user: src.security.UserDep, body: ChangeUsernameBody):
    db_user = session.exec(select(src.models.User).where(src.models.User.name == body.new_username)).first()
    if db_user:
        raise HTTPException(status_code=408, detail="Username already registered")

    user.name = body.new_username

    session.exec(update(src.models.User).where(src.models.User.id == user.id).values(name=body.new_username))  # type:ignore
    session.commit()


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


@router.post("/change_password")
def change_password(session: src.db.SessionDep, user: src.security.UserDep, body: ChangePasswordBody):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    new_password_hash = get_password_hash(body.new_password)

    user.password_hash = new_password_hash

    session.exec(update(src.models.User).where(src.models.User.id == user.id).values(password_hash=new_password_hash))  # type:ignore
    session.commit()


@internal.get("/users/names")
def user_names(session: src.db.SessionDep, ids: Annotated[list[int] | None, Query()] = None) -> dict[int, str]:
    """User id to name, for the ids that exist."""
    if not ids:
        return {}
    rows = session.exec(select(src.models.User).where(col(src.models.User.id).in_(ids))).all()
    return {row.id: row.name for row in rows if row.id is not None}
