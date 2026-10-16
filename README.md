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
