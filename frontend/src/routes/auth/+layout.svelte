<script lang="ts">
	import { goto } from "$app/navigation"
	import { getUserContext } from "$lib/types/User.svelte"

	const user = getUserContext()
	const { children } = $props()

	// Redirect to / if user is logged in (user != null)
	$effect(() => {
		if (user.current != null) {
			goto("/")
		}
	})
</script>

<!-- Prevents the form from flashing briefly before the user's auth state loads -->
{#if user.current == null}
	{@render children()}
{/if}
