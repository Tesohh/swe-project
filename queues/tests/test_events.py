import asyncio
import threading

from src.events import Broadcaster
from tests.helpers import create_room


def test_publish_from_other_thread_reaches_subscriber():
    async def run() -> dict:
        hub = Broadcaster()
        queue = hub.subscribe(1)
        threading.Thread(target=hub.publish, args=(1, {"topic": "queue"})).start()
        return await asyncio.wait_for(queue.get(), timeout=2)

    assert asyncio.run(run()) == {"topic": "queue"}


def test_other_room_gets_nothing():
    async def run() -> bool:
        hub = Broadcaster()
        queue = hub.subscribe(1)
        hub.publish(2, {"topic": "queue"})
        await asyncio.sleep(0.05)
        return queue.empty()

    assert asyncio.run(run())


def test_every_subscriber_gets_the_event():
    async def run() -> list[dict]:
        hub = Broadcaster()
        queues = [hub.subscribe(1), hub.subscribe(1)]
        hub.publish(1, {"n": 1})
        return [await asyncio.wait_for(q.get(), timeout=2) for q in queues]

    assert asyncio.run(run()) == [{"n": 1}, {"n": 1}]


def test_unsubscribe_stops_events():
    async def run() -> bool:
        hub = Broadcaster()
        queue = hub.subscribe(1)
        hub.unsubscribe(1, queue)
        hub.publish(1, {"topic": "queue"})
        await asyncio.sleep(0.05)
        return queue.empty()

    assert asyncio.run(run())


def test_unsubscribe_unknown_room_is_ok():
    Broadcaster().unsubscribe(5, asyncio.Queue())


def test_publish_without_subscribers_is_ok():
    Broadcaster().publish(5, {"topic": "queue"})


def test_sse_unknown_room_sends_missing(client):
    response = client.get("/room/999/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: room" in response.text
    assert '"type":"missing"' in response.text.replace(" ", "")


def test_room_id_route_does_not_shadow_mine(client):
    create_room(client)
    assert isinstance(client.get("/room/mine").json(), list)
