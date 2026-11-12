<script lang="ts">
	import qr from "qrcode-generator"
	import type { PageProps } from "./$types"
	import { onMount } from "svelte"
	import { Input } from "$lib/components/ui/input"
	import { Button } from "$lib/components/ui/button"

	onMount(() => {
		document.getElementById("placeholder").innerHTML = qrObj.createImgTag(4)
	})

	let { data }: PageProps = $props()
	async function handleSongRequest(songURL: string) {
		let res = await fetch(`/api/room/${data.room.id}/queue/request`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: songURL }) })

		if (!res.ok) {
			console.error("Song not found")
			return
		}

		let song = await res.json()

		//TEMP:
		res = await fetch(`/api/room/${data.room.id}/queue/temp_accept/${song.entry.id}`, { method: "PUT" })

		if (!res.ok) {
			console.error("Unable to accept the song")
			return
		}
	}
	let songURL = $state("")

	let qrObj = qr(4, "L")

	qrObj.addData(document.URL)
	qrObj.make()
</script>

<div class="flex h-full w-full flex-col items-center justify-center p-8">
	<div class="flex h-full w-1/2 flex-col gap-4">
		<div class="mb-8 flex w-full items-center justify-between gap-4">
			<h1 class=" text-2xl">Room: <span class="font-bold">{data.room.name}</span></h1>
			<div class="flex flex-col items-center gap-2">
				<span class="text-lg">JOIN HERE</span>
				<div class="" id="placeholder"></div>
				<span class="font-mono text-muted-foreground">[Code: {data.room.id}]</span>
			</div>
		</div>
		<div class=" flex flex-col gap-2 border-2 border-border bg-secondary p-2">
			<p class="text-lg font-bold">Request Song</p>
			<Input placeholder="Youtube URL" bind:value={songURL}></Input>
			<Button onclick={async () => await handleSongRequest(songURL)}>Add</Button>
		</div>
		<p class="text-xl">Songs:</p>
		{#each data.queue.order as item, i}
			{#if i == 0}
				<p class="text-lg">Now Playing:</p>
			{:else if i == 1}
				<p class="text-lg">In Queue:</p>
			{/if}
			<div class="flex flex-col gap-2 border-2 border-border bg-secondary p-2">
				<a href={item.song.source_url}>{item.song.title}</a>
				<audio src="/api/song/stream/{item.song_id}" controls></audio>
			</div>
		{/each}
	</div>
</div>
