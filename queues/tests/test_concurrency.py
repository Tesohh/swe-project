"""Writes to one room from many threads at once. The row lock on the room must keep the order valid."""

from concurrent.futures import ThreadPoolExecutor

from common.auth import CurrentUser
from sqlmodel import Session

import src.db
from src.queue import order
from tests.conftest import GUEST
from tests.helpers import add_queued, add_requested, check_invariants, create_room


def _in_session(func, *args):
    with Session(src.db.engine) as session:
        return func(session, *args)


def test_parallel_accepts_keep_dense_order(client, services):
    room = create_room(client)
    ids = [add_requested(client, room, song) for song in range(1, 9)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda entry: _in_session(order.accept_entry, room, entry), ids))

    check_invariants(room)


def test_parallel_moves_keep_dense_order(client, services):
    room = create_room(client)
    ids = [add_queued(client, room, song) for song in range(1, 7)]

    jobs = [(entry, position) for entry in ids for position in (0, 5, 2)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda job: _in_session(order.move, room, *job), jobs))

    check_invariants(room)


def test_parallel_votes_count_once_per_user(client, services):
    room = create_room(client)
    entry = add_requested(client, room, 1, GUEST)
    users = [CurrentUser(id=100 + n) for n in range(10)]

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda user: _in_session(order.set_vote, room, entry, user, 1), users * 2))

    with Session(src.db.engine) as session:
        assert order.score_of(session, entry) == 11
