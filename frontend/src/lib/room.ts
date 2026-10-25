export interface Room {
	id: number
	name: string
	user_id: number
	description?: string
	is_password_protected: boolean
}

export interface CreateRoomInput {
	name: string
	password?: string
	description?: string
}

/**
 * returns the rooms owned by the logged in user
 * - an array of rooms on success
 * - null on failure
 */
export async function getMyRooms(): Promise<Room[] | null> {
	const response = await fetch("/api/room/mine", {
		method: "GET",
		credentials: "include",
		headers: { Accept: "application/json" }
	})

	if (!response.ok) {
		return null
	}

	return (await response.json()) as Room[]
}

/**
 * - return a string with an error message if something went wrong
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
