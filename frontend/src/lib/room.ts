export interface CreateRoomInput {
	name: string
	password?: string
	description?: string
}

/**
 * this function returns:
 * - a string with an error message if something went wrong
 * - null if the room was created successfully.
 */
export async function createRoom(input: CreateRoomInput): Promise<string | null> {
	const response = await fetch("/api/room/create", {
		method: "POST",
		credentials: "include",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json"
		},
		body: JSON.stringify(input)
	})

	if (response.ok) {
		return null
	}

	const data = await response.json().catch(() => ({}))
	return data.detail ?? response.statusText ?? "Failed to create room"
}
