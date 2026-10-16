<script lang="ts">
	import { onMount } from "svelte"
	import { createUserState, setUserContext } from "$lib/types/User.svelte"
	import { ModeWatcher } from "mode-watcher"
	import "./layout.css"

	let { children } = $props()

	// Create user state
	const userState = createUserState()
	setUserContext(userState)

	onMount(async () => {
		await userState.refresh()
	})
</script>

<ModeWatcher />
<div class="flex h-screen w-full">
	{@render children()}
</div>
