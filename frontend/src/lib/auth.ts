import { parseUser, type User } from "./types/User.svelte.ts"

export function isValid(str: string): boolean {
	// letters: A-Z and a-z
	// numbers: 0-9
	// special characters: ~ ! @ # $ % ^ & * ( ) _ - + = { } [ ] | \ : ; " ' < , . > ? /

	if (!str) return false
	return /^[A-Za-z0-9~!@#$%^&*()_\-+={}[\]|\\:;"'<,.>?/]+$/.test(str)
}

/**
 * this function returns:
 * - a string representing an error message if something went worng
 * - null if everything is fine and the cookie was set correctly.
 * input validation **must** be done by the caller.
 */
export async function login(username: string, password: string): Promise<boolean> {
	const response = await fetch("/api/auth/token", {
		method: "POST",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/x-www-form-urlencoded"
		},
		body: new URLSearchParams({
			username: username,
			password: password
		})
	})

	if (response.ok) {
		return false
	}

	return true
}

export async function getUser(): Promise<User | null> {
	let res = await fetch("/api/auth/me", {
		credentials: "include"
	})

	if (!res.ok) {
		return null
	}

	return parseUser(await res.json())
}

export const register = async (username: string, password: string): Promise<boolean> => {
	const res = await fetch("/api/auth/signup", {
		method: "POST",
		headers: {
			"Content-Type": "application/json"
		},
		body: JSON.stringify({
			username: username,
			password: password
		})
	})

	if (res.status == 408) {
		return true
	} else if (!res.ok) {
		console.error(res.statusText)
		return true
	}
	return false
}
