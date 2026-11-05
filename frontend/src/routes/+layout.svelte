<script lang="ts">
	import { onMount } from "svelte"
	import { createUserState, setUserContext } from "$lib/types/User.svelte"
	import { ModeWatcher } from "mode-watcher"
	import "./layout.css"
	import { setSSEContext } from "$lib/sse"

	let { children } = $props()

	// Create user state
	const userState = createUserState()
	setUserContext(userState)

	const sseSource = new EventSource("/api/room/events", { withCredentials: true })
	setSSEContext(sseSource)

	sseSource.addEventListener("ping", (event) => {
		console.log("pong! (received `ping` SSE)")
	})

	onMount(async () => {
		await userState.refresh()
	})
</script>

<ModeWatcher />
<div class="flex h-screen w-full">
	{@render children()}
</div>
