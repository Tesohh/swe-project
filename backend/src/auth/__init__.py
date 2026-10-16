import datetime
import os
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from jose.exceptions import JWTError
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlmodel import Session, select

import src.db
import src.models

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120


class OAuth2PasswordCookie(OAuth2PasswordBearer):
    """OAuth2 password flow with token in a httpOnly cookie."""

    def __init__(self, *args, token_name: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._token_name = token_name or "jwt-token"

    @property
    def token_name(self) -> str:
        """Get the name of the token's cookie."""
        return self._token_name

    async def __call__(self, request: Request) -> str:
        """Extract and return a JWT from the request cookies.

        Raises:
            HTTPException: 403 error if no token cookie is present.
        """
        token = request.cookies.get(self._token_name)
        if not token:
            raise HTTPException(status_code=403, detail="Not authenticated")
        return token


class Token(BaseModel):
    access_token: str
    token_type: str


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordCookie(tokenUrl="auth/token")


class TokenData(BaseModel):
    id: int | None = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: datetime.timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, os.environ["JWT_SECRET_KEY"], algorithm=ALGORITHM)
    return encoded_jwt


def authenticate_user(session: Session, username: str, password: str) -> src.models.User | None:
    user = session.exec(select(src.models.User).where(src.models.User.name == username)).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(session: src.db.SessionDep, token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET_KEY"], algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        # token_data = TokenData(id=user_id)
    except JWTError:
        raise credentials_exception
    user = session.get(src.models.User, int(user_id))
    if user is None:
        raise credentials_exception
    return user


UserDep = Annotated[src.models.User, Depends(get_current_user)]
