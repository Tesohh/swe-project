"""JWT check and password hashing, shared by every service.

Only the auth service creates tokens. Every service checks them with the same secret,
and trusts the user id in the token. No service needs the users table to know who calls.
"""

import datetime
import os
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from jose.exceptions import JWTError
from passlib.context import CryptContext
from pydantic import BaseModel

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120
TOKEN_COOKIE = "jwt-token"


class OAuth2PasswordCookie(OAuth2PasswordBearer):
    """OAuth2 password flow with token in a httpOnly cookie."""

    def __init__(self, *args, token_name: str = TOKEN_COOKIE, **kwargs):
        super().__init__(*args, **kwargs)
        self._token_name = token_name

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


oauth2_scheme = OAuth2PasswordCookie(tokenUrl="auth/token")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


class CurrentUser(BaseModel):
    """The caller, as the token names them."""

    id: int


def create_access_token(
    data: dict, expires_delta: datetime.timedelta | None = None
) -> str:
    expire = datetime.datetime.now(datetime.UTC) + (
        expires_delta or datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return jwt.encode(
        {**data, "exp": expire}, os.environ["JWT_SECRET_KEY"], algorithm=ALGORITHM
    )


def user_id_from_token(token: str) -> int:
    """User id in token, or 401 if the token is not valid."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, os.environ["JWT_SECRET_KEY"], algorithms=[ALGORITHM]
        )
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exception
        return int(sub)
    except (JWTError, ValueError) as err:
        raise credentials_exception from err


def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    return CurrentUser(id=user_id_from_token(token))


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
