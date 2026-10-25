<script lang="ts">
	import { goto } from "$app/navigation"
	import { getUserContext } from "$lib/types/User.svelte"
	import { Button } from "$lib/components/ui/button/index.js"
	import { Label } from "$lib/components/ui/label/index.js"
	import { Input } from "$lib/components/ui/input/index.js"
	import * as Card from "$lib/components/ui/card/index.js"
	import Spinner from "$lib/components/ui/spinner/spinner.svelte"

	const user = getUserContext()

	let creds = $state({
		username: "",
		password: ""
	})

	let loading = $state<boolean>(false)

	async function handleRegister() {
		// if (!isValid(creds.username) || !isValid(password)) {
		// 	return
		// }

		loading = true

		let err = await user.register(creds.username, creds.password)

		if (!err) {
			err = await user.login(creds.username, creds.password)
			if (!err) goto("/")
			else console.error("Login error!")
		} else {
			console.error("Registration error!")
		}
	}
</script>

<div class="flex h-full w-full items-center justify-center">
	<Card.Root class="-my-4 w-full max-w-sm">
		<Card.Header>
			<Card.Title>Signup</Card.Title>
		</Card.Header>
		<Card.Content>
			<form>
				<div class="flex flex-col gap-6">
					<div class="grid gap-2">
						<Label for="username">Username</Label>
						<Input id="username" type="text" required bind:value={creds.username} />
					</div>
					<div class="grid gap-2">
						<Label for="password">Password</Label>
						<Input id="password" type="password" required bind:value={creds.password} />
					</div>
				</div>
			</form>
		</Card.Content>
		<Card.Footer class="flex-col gap-2">
			<Button type="submit" class="w-full" onclick={handleRegister} disabled={loading}>
				{#if loading}
					<Spinner />
				{/if}
				Sign up
			</Button>
			<Button variant="outline" class="w-full" onclick={() => goto("/auth/login")}>Login</Button>
		</Card.Footer>
	</Card.Root>
</div>
