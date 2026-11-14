# Drawing desk

Buildless local app served by `uv run stoa-chat` from the repository root. No Node
packages or build required. The backend serves external JS/CSS under its restrictive
content policy; uploaded SVG is never inserted into the page.

The smoke test uses real loopback HTTP and an isolated headless Brave profile. It
substitutes only `stoa.lanes.llm.chat` with controlled extraction facts, never final
answers. It uses generated public fixtures and makes no live model requests.

From the repository root, start the fixture in one terminal:

```sh
PYTHONPATH=backend/src uv run python frontend/tests/smoke_server.py
```

Start a fresh owned browser profile in another terminal (macOS example):

```sh
"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" --headless --disable-gpu --no-first-run --no-default-browser-check --remote-debugging-port=9224 --user-data-dir=/private/tmp/stoa42-brave about:blank
```

With Node 22+ (global WebSocket), run `node frontend/tests/smoke.mjs`. The test
creates a chat, uploads PNG/SVG together, selects scope, asks in Finnish, inspects
a correctly scaled highlight with focus/zoom and pan, follows up with estimate and insufficient-volume
questions, resumes after reload, uploads a generated 51 MiB IFC through the browser,
and deletes the chats. It captures desktop/mobile
screenshots under `/private/tmp/stoa42-*.png`, checks mobile width and JS exceptions.
Stop the owned fixture server/browser afterwards. Fixture storage is
`/private/tmp/stoa42-browser-data`; use a fresh directory/profile for isolated runs.

Large PNG/JPEG answers show completed/required image-region coverage. Evidence stays
in original source coordinates even when extracted from detailed crops. The smoke
fixture exercises that coverage and crop-to-original highlight alignment. For an
isolated run, set `STOA_SMOKE_STORAGE`/`STOA_SMOKE_PORT` on the fixture server and
`STOA_SMOKE_CDP_URL`/`STOA_SMOKE_APP_URL` on the Node smoke script.
