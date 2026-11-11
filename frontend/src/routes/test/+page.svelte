<script lang="ts">
	import { Button } from "$lib/components/ui/button"
	import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "$lib/components/ui/card"
	import type { Song } from "$lib/song"
	import { getSong, streamUrl } from "$lib/song"

	// the song is stored as songs/<id> on the backend, so id 1 is songs/1.mp3
	const TEST_SONG_ID = 1

	let song = $state<Song | null>(null)
	let missing = $state(false)
	let rangeReport = $state("")

	$effect(() => {
		;(async () => {
			const result = await getSong(TEST_SONG_ID)
			song = result
			missing = result == null
		})()
	})

	function formatDuration(seconds: number | null): string {
		if (seconds == null) return "unknown length"
		const minutes = Math.floor(seconds / 60)
		const rest = Math.floor(seconds % 60)
		return `${minutes}:${rest.toString().padStart(2, "0")}`
	}

	async function probeRange(): Promise<void> {
		const response = await fetch(streamUrl(TEST_SONG_ID), { headers: { Range: "bytes=0-1023" } })
		const bytes = await response.arrayBuffer()
		rangeReport = `${response.status} | content-range: ${response.headers.get("content-range")} | bytes: ${bytes.byteLength}`
	}
</script>

<div class="flex h-full w-full items-center justify-center">
	<Card class="w-80">
		<CardHeader>
			<CardTitle>Test stream of song {TEST_SONG_ID}</CardTitle>
			<CardDescription>
				{song ? song.title : missing ? "song 1 is not in the songs table" : "loading song info..."}
			</CardDescription>
		</CardHeader>
		<CardContent class="flex flex-col gap-3">
			{#if song}
				<div class="text-sm text-muted-foreground">
					<div>{song.artist ?? song.uploader ?? "no artist"}</div>
					<div>{formatDuration(song.duration)} | file {song.filename}</div>
				</div>

				<!-- Range requests work through the caddy proxy, so seeking works -->
				<audio class="w-full" src={streamUrl(TEST_SONG_ID)} controls></audio>

				<Button variant="secondary" onclick={probeRange}>Ask for the first 1024 bytes</Button>
				{#if rangeReport}
					<div class="text-xs break-all text-muted-foreground">{rangeReport}</div>
				{/if}
			{/if}
		</CardContent>
	</Card>
</div>
