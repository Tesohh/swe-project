<script lang="ts">
	import { goto } from "$app/navigation"
	import Button from "$lib/components/ui/button/button.svelte"
	import { getUserContext } from "$lib/types/User.svelte"

	const user = getUserContext()

	$effect(() => {
		if (user.current == null) {
			goto("/auth/login")
		}
	})
</script>

<!-- Prevents the text from flashing briefly before the user's auth state loads -->
{#if user.current != null}
	<div class="flex h-full w-full items-center justify-center">
		<div class="flex flex-col gap-2">
			<h1 class="text-2xl">Ciao, {user.current?.name}</h1>
			<Button onclick={() => user.logout()}>Logout</Button>
		</div>
	</div>
{/if}
