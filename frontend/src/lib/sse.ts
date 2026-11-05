import { createContext } from "svelte"

export const [getSSEContext, setSSEContext] = createContext<EventSource>()
