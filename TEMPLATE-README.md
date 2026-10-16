# SWE Project (Music App)

## Production
This app is designed to run under docker. 
It might run without, but no guarantees!

Prerequisites for running in production:
- `docker` or any compatible alternative (eg. `podman`)
- `postgres` container running
- (recommended) `docker-compose` or any compatible alternative (eg. `podman-compose`)
- (recommended) `traefik` container running, or any other reverse proxy

**The way you deploy it depends *heavily* on your server circumstances.**

Dockerfile for frontend and backend are at `frontend/Dockerfile` and `backend/Dockerfile` respectively.

<details>
<summary>Example docker compose</summary>

```yml
networks:
  main_network:
    external: true

services:
  frontend:
    restart: unless-stopped
    build:
      context: ./hackathon/frontend
    networks:
      - main_network
    env_file:
      - .env
    labels:
      - traefik.enable=true
      - traefik.http.routers.hackathon.rule=Host(`hackathon.pausetta.org`)
      - traefik.http.routers.hackathon.entrypoints=websecure
      - traefik.http.routers.hackathon.tls.certresolver=le
      - traefik.http.services.hackathon.loadbalancer.server.port=5173

  backend:
    restart: unless-stopped
    build:
      context: ./hackathon/backend
    environment:
      - DATABASE_URL=YOUR_DB_URL
      - JWT_SECRET_KEY=PUT_ANYTHING_HERE
    networks:
      - main_network 
    labels:
      - traefik.enable=true
      - traefik.http.routers.hackathon-back.rule=Host(`hackathon.pausetta.org`) && PathPrefix(`/api`)
      - traefik.http.routers.hackathon-back.entrypoints=websecure
      - traefik.http.routers.hackathon-back.tls.certresolver=le
      - traefik.http.services.hackathon-back.loadbalancer.server.port=8000
```
</details>

## Development

### Running
To run the development docker compose:
```bash
docker compose up
```
See the *Tips* section for some nice development tools.

### Style guidelines

If you push any code to the repo you MUST follow these guidelines:
- ALL code has to be in english (including comments)
- ALL python code has to pass through the `ruff` formatter
- ALL python code has to have 0 errors from `ty` type checker
- ALL python identifiers have to be `snake_case`
- ALL svelte/js/ts/html/css/json code has to pass through the `prettier` formatter
- ALL svelte/js/ts identifiers have to be `camelCase`
- ALL svelte code has to use the new runes syntax (eg. `$state`, `$effect`...) instead of the old implicit reactivity
- TRY to keep code files under 2 pages, ideally 1
- AVOID writing raw css unless it's the only option. we only use raw css for defining the theme and a few utility classes.

### Backend

#### Prerequisites
If you're also going to work on the backend:
- `uv`
- `ty` (not required but highly recommended for best language support)
- `ruff` (required if you're going to push code. or else you will be purged)

#### Setup
```bash
cd backend
uv sync
```
done. If you have `ty` installed in your editor, language features should work right away

### Frontend

#### Prerequisites
If you're also going to work on the frontend:
- `npm` or any alternative (eg. `pnpm`)
- `prettier` (required if you're going to push code. or else you will be purged)
- `svelte-language-server` (not required but highly recommended for best language support)

#### Setup
```bash
cd frontend
npm i
```

#### Hot Reloading Docker Fix
If you're using `docker` (not `podman`) you might have issues with hot reloading vite.
If that's the case, add this line to your `.env`:
```env
DOCKER_POLLING_FIX = yes
```

### Tips
The development docker compose (and FastAPI) also starts some other useful services:
- OpenAPI (ex Swagger) UI: accessible from `localhost:8080/api/docs`
- ReDoc UI (swagger ui alternative): accessible from `localhost:8080/api/redoc`
- Adminer (database admin panel): accessible from `localhost:8080/adminer/` (trailing `/` is significant)
    - System: `PostgreSQL`
    - Server: `postgres`
    - Username: `root`
    - Password: `root`
    - Database: `hackathon`
