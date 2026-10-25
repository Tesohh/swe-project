# Project summary
- this is a shared music queue app so people can vote on what plays (for live events, bars, beaches, public places)
- the queue is manually moderated (no ai model for the moment)
- runs on docker-compose: `caddy` (routing), `frontend`, `backend`, `postgres`, `adminer`
- `frontend` is a `sveltekit` app with two clients:
  - user client to add/share songs
  - player client to manage the queue and show info
- `backend` is a `fastapi` python server:
  - downloads/strips songs with `yt-dl`
  - handles `auth` (jwt), `room` (queues), `song`, and `ws` (websocket for live updates)
  - `postgres` for storage
- qr code system to join a room/queue

# Frontend
- The project uses `shadcn-svelte` for frontend components
- `shadcn` is a component library where you only add what you need
- `shadcn` components are added via the `pnpm dlx shadcn-svelte@latest add <component name> -y`
- Before writing a custom component, always try looking in the `shadcn-svelte` docs if there is something already made
    - if not, build upon `shadcn-svelte` components if possible

# Backend
- The backend is built on `fastapi` and `sqlmodel`
- The dbms is `postgres` which always runs as a docker container
- The backend uses `uv` as the package manager, never try to do things via `pip` directly
