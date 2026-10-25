<script lang="ts">
	import { z } from "zod"
	import Button from "$lib/components/ui/button/button.svelte"
	import { buttonVariants } from "$lib/components/ui/button/index.js"
	import Input from "$lib/components/ui/input/input.svelte"
	import * as Field from "$lib/components/ui/field/index.js"
	import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from "$lib/components/ui/dialog/index.js"
	import { createRoom, type CreateRoomInput } from "$lib/room"

	let { open = $bindable(false), onSubmit } = $props()

	const schema = z.object({
		name: z.string().trim().min(1, "Room name is required")
	})
	type FormInput = z.infer<typeof schema>

	let form = $state<FormInput>({ name: "" })
	let password = $state("")
	let description = $state("")
	let error = $state<string | null>(null)
	let submitting = $state(false)

	function resetForm() {
		form = { name: "" }
		password = ""
		description = ""
		error = null
	}

	// clear the form each time the dialog opens
	$effect(() => {
		if (open) resetForm()
	})

	async function handleSubmit(event: SubmitEvent) {
		event.preventDefault()
		const parsed = schema.safeParse(form)
		if (!parsed.success) {
			error = parsed.error.issues[0].message
			return
		}
		error = null
		submitting = true

		const input: CreateRoomInput = {
			name: form.name,
			password: password || undefined,
			description: description || undefined
		}
		const createError = await createRoom(input)

		submitting = false
		if (createError) {
			error = createError
			return
		}

		open = false
		onSubmit?.()
	}
</script>

<Dialog bind:open>
	<DialogTrigger class={buttonVariants({ variant: "default", size: "default" })}>New Room</DialogTrigger>
	<DialogContent class="gap-4">
		<DialogHeader>
			<DialogTitle>Create a new room</DialogTitle>
			<DialogDescription>Give your room a name. You can add a password and description too.</DialogDescription>
		</DialogHeader>

		<form class="gap-4" onsubmit={handleSubmit}>
			<Field.Group class="gap-3">
				<Field.Field>
					<Field.Label for="room-name">Room name</Field.Label>
					<Field.Content>
						<Input id="room-name" bind:value={form.name} type="text" placeholder="eg. Silvy Bar" autocomplete="off" disabled={submitting} />
					</Field.Content>
					{#if error && error.startsWith("Room")}
						<Field.Error>{error}</Field.Error>
					{/if}
				</Field.Field>

				<Field.Field>
					<Field.Label for="room-password">Password (optional)</Field.Label>
					<Field.Content>
						<Input id="room-password" bind:value={password} type="password" placeholder="Leave blank for no password" autocomplete="off" disabled={submitting} />
					</Field.Content>
				</Field.Field>

				<Field.Field>
					<Field.Label for="room-description">Description (optional)</Field.Label>
					<Field.Content>
						<Input id="room-description" bind:value={description} type="text" placeholder="What music will you listen to?" autocomplete="off" disabled={submitting} />
					</Field.Content>
				</Field.Field>
			</Field.Group>

			{#if error && !error.startsWith("Room")}
				<p class="text-sm font-normal text-destructive" role="alert">{error}</p>
			{/if}

			<DialogFooter class="mt-2">
				<DialogClose class={buttonVariants({ variant: "outline" })} type="button">Cancel</DialogClose>
				<Button type="submit" disabled={submitting}>
					{submitting ? "Creating..." : "Create"}
				</Button>
			</DialogFooter>
		</form>
	</DialogContent>
</Dialog>
