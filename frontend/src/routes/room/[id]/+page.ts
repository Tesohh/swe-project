import { error } from "@sveltejs/kit"

export async function load({ params }) {
	let roomId = params.id

	let res = await fetch(`/api/room/${roomId}`, { method: "GET" })

	if (!res.ok) {
		return { room: null, error: "Room not found" }
	}

	let room = await res.json()
	console.log(room)

	res = await fetch(`/api/room/${roomId}/queue`, { method: "GET" })

	if (!res.ok) {
		return { room: null, queue: null, error: "Queue not found" }
	}

	let queue = await res.json()
	console.log(queue)

	const sseSource = new EventSource(`/api/room/${roomId}/events`, { withCredentials: true })

	sseSource.addEventListener("queue", (event) => {
		console.log("queue update", JSON.parse(event.data))
	})

	return { room, queue, sseSource, error: null }
}
