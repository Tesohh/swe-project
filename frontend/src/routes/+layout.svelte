<script lang="ts">
	import { onMount } from "svelte"
	import { createUserState, setUserContext } from "$lib/types/User.svelte"
	import { ModeWatcher } from "mode-watcher"
	import "./layout.css"
	// import { setSSEContext } from "$lib/sse"

	let { children } = $props()

	// Create user state
	const userState = createUserState()
	setUserContext(userState)

	// SSE connect, starts when the client picks a room to follow
	// const sseSource = new EventSource(`/api/room/${room_id}/events`, { withCredentials: true })
	// setSSEContext(sseSource)

	// sseSource.addEventListener("queue", (event) => {
	// 	console.log("queue update", JSON.parse(event.data))
	// })

	onMount(async () => {
		await userState.refresh()
	})
</script>

<ModeWatcher />
<div class="flex h-screen w-full">
	{@render children()}
</div>
