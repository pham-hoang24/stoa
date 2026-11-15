// The drawing chat is served by `uv run stoa-chat` at /chat. When the landing
// page runs on the Vite dev server, set VITE_CHAT_URL=http://127.0.0.1:8092/chat.
export const CHAT_URL: string = import.meta.env.VITE_CHAT_URL ?? "/chat"
