export interface Song {
	id: number
	title: string
	artist: string | null
	uploader: string | null
	duration: number | null
	source_id: string | null
	source_url: string | null
	genre: string | null
	mood: string | null
	quality: string | null
	filename: string | null
}

/** url of the audio file served by the backend, used by an audio element */
export function streamUrl(songId: number): string {
	return `/api/song/stream/${songId}`
}

/**
 * returns the song row of songId
 - the song on success
 - null on failure
 */
export async function getSong(songId: number): Promise<Song | null> {
	const response = await fetch(`/api/song/info/${songId}`, {
		method: "GET",
		headers: { Accept: "application/json" }
	})

	if (!response.ok) {
		return null
	}

	const data = await response.json()
	return (data.song as Song) ?? null
}
