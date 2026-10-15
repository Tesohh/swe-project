# Who is this for / what problem it solves

This project helps to create a shared music queue
so that people can more "democratically" choose which music to listen to,
instead of leaving it up to the venue.

It is meant for

- live events
- bars
- beaches
- other public places

# MVP requirements

- `Sveltekit` Frontend
  - Basic user client (for sharing songs)
  - Basic player client (for managing queue and showing info)
- `fastapi` python server
  - for downloading/streaming songs with `yt-dl`
- QR Code system
- Manually moderated queue system (no AI model for now)

# Backlog

We have a custom built issue tracker and will use that to track our user stories.

## +feat +mvp Scaffold the project with template

**As a** developer, **I want** to have the template ready **so that** we can then build the MVP.
Acceptance criteria:

- have the `https://gitlab.com/lallo.segala/hackathon-template` template in the github repo
- the project must build and run under windows, linux and macos inside podman/docker containers

## +feat +mvp Add sqlite DB

**As a** developer, **I want** a sqlite3 database **so that** we can persist room and song data.
Acceptance criteria:

- The backend server can interact with the DB through `SQLModel`

## +feat +mvp Add basic music downloading system

**As a** developer,
**I want** a system for downloading songs from youtube using `yt-dl`
**so that** the player can play them.
Acceptance criteria:

- A system for downloading a song from youtube from a URL
- The server saves the audio file and returns a song ID

## +feat +mvp Search for songs

**As a** guest, **I want** to search for a song by text **so that** I can find it fast.

Acceptance criteria:

- The server returns a list of results with title, artist, duration, and thumbnail
- A guest can also paste a URL

## +feat +mvp Stream songs

**As a** player client, **I want** to stream a downloaded song **so that** playback starts without delay.

Acceptance criteria:

- A FastAPI endpoint streams audio by song ID
- The player client plays the stream in a browser

## +feat +mvp Create a room

**As a** host, **I want** to create a room **so that** guests can join it.

Acceptance criteria:

- The host gets a unique room ID.
- The server stores the room and its queue.

## +feat +mvp Generate a QR code

**As a** host, **I want** a QR code for my room **so that** guests can join fast.

Acceptance criteria:

- The QR code contains the room URL.
- The player client shows the QR code.

## +feat +mvp Join a room

**As a** guest, **I want** to scan the QR code **so that** I join the room.
Acceptance criteria:

- The scan opens the user client in the correct room
- The user client shows an error message if the room does not exist

## +feat +mvp Add a song to the queue

**As a** guest, **I want** to add a song from my smartphone **so that** it plays at the event.
Acceptance criteria:

- The user client can paste a youtube URL
- The song appears in the queue

## +feat +mvp Setup websocket

**As a** developer, **I want** a websocket system **so that** we can build realtime features.
Acceptance criteria:

- The user clients and player client are able to connect to the server websocket
- A basic test `ping` message verifies the connection

## +feat +mvp Update the queue in real time

**As a** guest, **I want** to see queue changes immediately **so that** I know when my song plays.

Acceptance criteria:

- The server sends queue changes through WebSocket
- All clients in the room update in less than 2 seconds

## +feat +mvp Play the queue

**As a** host, **I want** the player client to play the songs in order **so that** the music does not stop.

Acceptance criteria:

- The player client starts the next song when the current song ends
- The player client shows the current song

## +feat +mvp Show the queue on a large screen

**As a** host, **I want** a screen view with the queue and QR code **so that** guests see what plays next.

Acceptance criteria:

- The view shows the current song, the next songs, and the QR code
- The text is readable from 5 meters

## +feat +mvp Moderate the queue

**As a** host, **I want** to skip, remove, and reorder songs **so that** I control the music in case the AI gets something wrong.

Acceptance criteria:

- The host can skip the current song.
- The host can remove a song and drag a song to a new position.

## +feat +mvp Block duplicate songs (ID based)

**As a** guest, **I want** the queue to reject a song that is already in it **so that** the same song does not play twice.
Acceptance criteria:

- The server rejects a song with the same ID as a queued song
- The user client shows a clear message

# Ideas for the future

- Spotify-style remote player, so that you can listen in on the queue from remote (eg. share a queue with a friend)

## AI model(s) / features

### Custom trained audio model

- Recognize genre of song to feed into the "smart shuffle" feature
- Filter songs by genre

### Decision model

- Pick best version of song (avoid music videos, concert recordings, intros... etc.)
- Resolve duplicates (even with similar songs)
- "Smart shuffle" (order the queue in a smart way to avoid too much repetition and keep things interesting)
