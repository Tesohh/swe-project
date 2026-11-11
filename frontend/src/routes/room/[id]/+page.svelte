<script lang="ts">
	import type { PageProps } from "./$types"
	let { data }: PageProps = $props()
</script>

<div class="flex h-full w-full flex-col items-center justify-center gap-8 p-8">
	<h1 class=" text-2xl">Room: <span class="font-bold">{data.room.name}</span></h1>
	<div class="flex h-full w-1/2 flex-col gap-4">
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
