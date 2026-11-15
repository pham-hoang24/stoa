# Stoa landing page

Vite + React + Tailwind v4 + shadcn/ui. Static build.

```
cd web
pnpm install
pnpm dev      # http://localhost:5173
pnpm build    # dist/
```

The backend serves `web/dist` at `/` and the chat app at `/chat` (`uv run stoa-chat`,
`--landing` overrides the directory). "Open the chat" links use `/chat`; when running
`pnpm dev`, set `VITE_CHAT_URL=http://127.0.0.1:8092/chat`.

On Vercel, `vercel.json` redirects `/chat` to the Render service
(`https://stoa-80wy.onrender.com/chat`). Override with `VITE_CHAT_URL` at build time
if the chat host changes. Render start command: `uv run stoa-chat --host 0.0.0.0`.
