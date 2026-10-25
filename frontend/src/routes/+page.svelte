<script lang="ts">
	import Button from "$lib/components/ui/button/button.svelte"
	import CreateRoomDialog from "$lib/components/CreateRoomDialog.svelte"
	import type { Room } from "$lib/room"
	import { getMyRooms } from "$lib/room"
	import { getUserContext } from "$lib/types/User.svelte"
	import LockIcon from "@lucide/svelte/icons/lock"

	const user = getUserContext()
	let newRoomOpen = $state(false)
	let rooms = $state<Room[] | null>(null)

	// fetch the rooms once the user is known
	// TODO: use skeletons while loading?
	$effect(() => {
		if (user.current == null) return
		;(async () => {
			rooms = await getMyRooms()
		})()
	})

	async function handleCreated() {
		newRoomOpen = false
		user.refresh()
		rooms = await getMyRooms()
	}
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
				<CreateRoomDialog bind:open={newRoomOpen} onSubmit={handleCreated} />
				<Button variant="secondary" onclick={() => user.logout()}>Logout</Button>
			</div>
			{#if rooms == null}
				<div class="bg-secondary p-4">Loading...</div>
			{:else}
				{#each rooms as room (room.id)}
					<a class="bg-secondary p-4" href="/room/{room.id}">
						<div class="flex items-center justify-between gap-2">
							<div class="min-w-0">
								<div class="font-bold">{room.name}</div>
								{#if room.description}
									<div class="text-sm text-muted-foreground">{room.description}</div>
								{/if}
							</div>
							{#if room.is_password_protected}
								<span class="text-lg text-muted-foreground" title="password protected"><LockIcon size={16} /></span>
							{/if}
						</div>
					</a>
				{/each}
			{/if}
		</div>
	</div>
{/if}
