# Project summary
- this is a shared music queue app so people can vote on what plays (for live events, bars, beaches, public places)
- the queue is manually moderated (no ai model for the moment)
- runs on docker-compose: `caddy` (api gateway), `frontend`, the services below, `postgres`, `adminer`
- `frontend` is a `sveltekit` app with two clients:
  - user client to add/share songs
  - player client to manage the queue and show info
- the backend is split into `fastapi` python services, one per bounded context (see `documentation/concept-map.typ`). Each service has its own dir, `pyproject.toml` (`uv`), Dockerfile and its own `postgres` container:
  - `common`: library (not a service) with the JWT check, password hashing and the HTTP client for service-to-service calls
  - `auth`: users and login (jwt cookie). Postgres `postgres-auth`
  - `songs`: song catalog, downloads/strips songs with `yt-dlp`, streams audio. Postgres `postgres-songs`
  - `queues`: rooms, queues, votes, and `sse` (live updates, not websocket). Postgres `postgres-queues`
  - `inference`: the audio tagger (torch), called by `songs`
  - `decision` (`llama.cpp`) comes later
- `caddy` is the only gateway: the frontend talks to `/api/auth`, `/api/song`, `/api/room`. Services call each other directly (e.g. `http://songs:8000`), never through `caddy`
- a service never reads the postgres of another service. It keeps ids and asks the other service over HTTP (`/internal/...` routes, which `caddy` does not route)
- there is one `postgres` container per service (`postgres-auth`, `postgres-songs`, `postgres-queues`), each with its own volume. `adminer` can open all three
- qr code system to join a room/queue

# Frontend
- The project uses `shadcn-svelte` for frontend components
- `shadcn` is a component library where you only add what you need
- `shadcn` components are added via the `pnpm dlx shadcn-svelte@latest add <component name> -y`
- Before writing a custom component, always try looking in the `shadcn-svelte` docs if there is something already made
    - if not, build upon `shadcn-svelte` components if possible

# Backend
- The services are built on `fastapi` and `sqlmodel`
- The dbms is `postgres` which always runs as a docker container
- The services use `uv` as the package manager (one `uv.lock` per service), never try to do things via `pip` directly
- Python services build with the repo root as docker context, because they install `./common`
- Shared code goes into `common`. Do not import one service from another
