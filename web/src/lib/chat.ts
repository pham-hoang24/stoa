// The drawing chat runs locally (`uv run stoa-chat`, served at /chat). On a
// local host the CTAs open it; on the public site they jump to the setup steps.
// With the Vite dev server, set VITE_CHAT_URL=http://127.0.0.1:8092/chat.
export const IS_LOCAL: boolean =
  typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname)

export const CHAT_URL: string =
  import.meta.env.VITE_CHAT_URL ?? (IS_LOCAL ? "/chat" : "#run")
