<script lang="ts">
	import Button from "$lib/components/ui/button/button.svelte"
	import { getUserContext } from "$lib/types/User.svelte"

	const user = getUserContext()
</script>

{#if user.current == null}
	<div class="flex h-full w-full items-center justify-center">
		<div class="flex flex-col gap-2">
			<h1 class="text-2xl font-bold">Hi</h1>
			<p>Join a room by scanning a <b class="text-accent">QR code</b> <br />or <b class="text-accent">login</b> to create a room</p>
			<Button href="/auth/login">Login</Button>
		</div>
	</div>
{:else}
	<div class="flex h-full w-full items-center justify-center">
		<div class="flex w-56 flex-col gap-2">
			<h1 class="text-2xl">Hello, {user.current?.name}</h1>
			<div class="flex flex-row">
				<Button onclick={() => user.logout()}>New Room</Button>
				<Button variant="secondary" onclick={() => user.logout()}>Logout</Button>
			</div>
			<div class="flex flex-col gap-y-2">
				<div class="bg-secondary p-4">Room A</div>
				<div class="bg-secondary p-4">Room B</div>
				<div class="bg-secondary p-4">Room C</div>
			</div>
		</div>
	</div>
{/if}
