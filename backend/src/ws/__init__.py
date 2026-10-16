import logging
from enum import Enum
from typing import Any, Dict

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel

router = APIRouter(prefix="/trade")

log = logging.getLogger(__name__)


class MessageRecvMethod(Enum):
    PING = "ping"


class MessageRecv(BaseModel):
    method: MessageRecvMethod
    from_user_id: int
    to_user_id: int | None  # none if from server
    data: Dict[str, Any]


class MessageSendMethod(Enum):
    PONG = "pong"


class MessageSend(BaseModel):
    method: MessageSendMethod
    from_user_id: int | None  # none if from server
    data: Dict[str, Any]


class Room:
    name: str
    sockets: Dict[int, WebSocket] = {}

    def __init__(self, name: str):
        self.name = name

    async def join(self, user_id: int, ws: WebSocket):
        if user_id in self.sockets:
            log.info(f"user {user_id} is already in room {self.name}! rejoining them..")

        await ws.accept()
        log.info(f"user {user_id} joined room {self.name}")
        self.sockets[user_id] = ws

    async def leave(self, user_id: int):
        if user_id not in self.sockets:
            return

        log.info(f"user {user_id} left room {self.name}")
        del self.sockets[user_id]

    async def send(self, to_user_id: int, msg: MessageSend):
        if msg.from_user_id not in self.sockets or to_user_id not in self.sockets:
            return
        msg_bytes = msg.model_dump_json()
        await self.sockets[to_user_id].send_json(msg_bytes)
