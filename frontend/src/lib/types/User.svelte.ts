import { getUser, login, register } from "$lib/auth"
import { createContext } from "svelte"
import * as z from "zod"

const UserSchema = z.object({
	id: z.number(),
	name: z.string(),
	credits: z.number().optional()
})

export type User = z.infer<typeof UserSchema>

export const parseUser = (data: any): User | null => {
	const res = UserSchema.safeParse(data)

	if (!res.success) {
		console.error(res.error.message)
		return null
	}
	return res.data
}

export function createUserState() {
	// $state variable for the user
	let current = $state<User | null>(null)

	return {
		get current(): User | null {
			return current
		},
		async refresh() {
			current = await getUser()
		},
		login: async (user: string, pass: string) => {
			const err = await login(user, pass)

			// Update the user $state variable
			if (!err) current = await getUser()

			return err
		},
		register: register,
		async logout() {
			await fetch("/api/auth/logout", { method: "POST", credentials: "include" })
			current = null
		}
	}
}

export const [getUserContext, setUserContext] = createContext<ReturnType<typeof createUserState>>()
