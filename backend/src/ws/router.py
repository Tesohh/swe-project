import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.ws import MessageRecv, MessageRecvMethod, MessageSend, MessageSendMethod, Room

log = logging.getLogger(__name__)
room = Room("general")
router = APIRouter(prefix="/ws")


class StartTradeBody(BaseModel):
    to_user_id: int

    give_card_id: str
    give_card_amount: int

    take_card_id: str
    take_card_amount: int


@router.websocket("/{user_id}")
async def websocket_endpoint(ws: WebSocket, user_id: int):
    await room.join(user_id, ws)
    try:
        while True:
            data = await ws.receive_text()
            msg = MessageRecv.model_validate_json(data)

            log.info("got message %s", vars(msg))

            match msg.method:
                case MessageRecvMethod.PING:
                    await room.send(msg.from_user_id, MessageSend(method=MessageSendMethod.PONG, from_user_id=None, data={}))

    except WebSocketDisconnect:
        await room.leave(user_id)
