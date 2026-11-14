# Local drawing chat backend

Package `stoa_chat`, `create_server(storage_root, host='127.0.0.1', port=8092, answerer=None, max_upload_bytes=52428800, allowed_origins=(), static_dir=None, max_ifc_upload_bytes=536870912)` returns stdlib ThreadingHTTPServer. Caller runs serve_forever/shutdown/server_close. New backend only, independent from legacy benchmark.

- POST /api/chats JSON {title?} → 201 chat
- GET /api/config → {upload_limits: {default: bytes, ifc: bytes}}; frontend validation uses these active limits.
- GET /api/chats → chat array; GET /api/chats/{chat_id} → complete chat including drawings, selected_drawing_ids, messages
- DELETE /api/chats/{chat_id} → 200 {deleted:id}; reference-aware content asset cleanup
- POST /api/chats/{chat_id}/uploads?filename=plan.png → raw bytes → 201 drawing {id,filename,sha256,format,media_type,pages,asset_url}; PNG/JPEG/PDF/IFC/DXF/SVG. IDs random, bytes content-addressed.
- POST /api/chats/{chat_id}/questions JSON {question, drawing_ids?:[id]} → assistant message {id,role:'assistant',drawing_ids,answer}. Omitted drawing_ids inherits prior selected scope; first question must select explicitly. User and assistant messages persisted. Unknown/empty selections 400.
- GET /api/chats/{chat_id}/assets/{drawing_id} → original source bytes, chat-scoped.
- GET /api/chats/{chat_id}/evidence/{assistant_message_id}/{index} → evidence JSON, chat-scoped.
- GET /api/chats/{chat_id}/previews/{drawing_id}/{page} → safe PNG with source mapping retained on evidence.
- Errors JSON {error: readable string}, 400/403/404/413.

Injected `answerer(context: dict) -> dict` is synchronous. Context: question, drawing_ids, messages (prior messages only), drawings (selected drawing metadata plus backend-private pathlib Path in `path`). Paths never sent over HTTP. Each drawing's pages has page (one-based), width,height,units where available. Metadata format lowercase png/jpeg/pdf/ifc/dxf/svg.

Answer dict: status supported/proposal/estimate/clarification/abstain, value number/string/null, unit optional, explanation, evidence list. Extra serializable fields preserved (calculation, review status, etc). Evidence: drawing_id, page (one-based when paginated), bbox [x0,y0,x1,y1] optional in page source coordinates, entity_id optional. Backend adds evidence.url. Non-abstain substantive answers require scoped resolvable evidence; invalid answer output becomes persisted abstain. The default hybrid engine uses native source facts first, then bounded extraction through the configured provider when needed. Native answers remain distinct from unreviewed visual proposals. Exceptions become analysis_error abstains and preserve previous history.

Tests: actual ephemeral loopback HTTP; run with PYTHONPATH=backend/src /path/to/.venv/bin/python -m pytest backend/tests -q. Sandbox requires socket permission. No live-provider calls.

## Local commands

From the repository root, with its existing dependencies installed:

```
PYTHONPATH=backend/src .venv/bin/python -m stoa_chat --storage .cache/chat --port 8092
PYTHONPATH=backend/src .venv/bin/python -m pytest backend/tests -q
```

The CLI serves repository `frontend/` at `/` by default; `--frontend` overrides that directory; it does not modify the pitch site. Scripts must be external files because the frontend content policy does not permit inline JavaScript. Original SVG is served with a restrictive sandbox policy; callers should render evidence safely rather than inserting SVG source into HTML.

Provider selection is server-side. NVIDIA is the default, using `NVIDIA_API_KEY`
and `nvidia/nemotron-3.5-super-vl-120b-a12b` at `https://integrate.api.nvidia.com/v1`.
`--llm-provider` overrides `STOA_LLM_PROVIDER`. NVIDIA timeouts (SDK timeout or HTTP
408/504) may use one selected secondary: `--llm-fallback modal|featherless|none`
overrides `STOA_LLM_FALLBACK` (default Modal). Other API errors do not fall through;
a secondary timeout ends the chain. SDK retries remain disabled. Each model call permits
at most two live attempts, which
share the process request cap; cached replies remain free and endpoint-specific.

`--llm-timeout-seconds` overrides positive finite `STOA_LLM_TIMEOUT_SECONDS`
(default 60 per attempt). NVIDIA uses `STOA_NVIDIA_BASE_URL`/`STOA_NVIDIA_MODEL`
overrides, Modal uses `MODAL_API_KEY` with `STOA_MODAL_BASE_URL`/`STOA_MODAL_MODEL`,
and Featherless retains its existing `STOA_LLM_*` overrides. Explicit Modal or
Featherless primary selection does not start the NVIDIA fallback chain.
`model_provenance` reports the producing provider/model, cache status, and
`fallback_from`/`fallback_reason` when used. Multi-file totals retain per-drawing
provenance and identify mixed providers explicitly. No credential is included.
See the root README for runnable configuration.

The server stores chat JSON transactionally in SQLite and originals under SHA-256 filenames in `assets/`. Asset creation uses atomic replacement before the chat transaction commits. Deleting a chat retains material referenced by other chats; restart also removes orphaned temporary or unreferenced assets. Run one backend process per storage directory. Storage is local and has no accounts or cloud synchronization.

Default upload limits are 512 MiB for IFC (`max_ifc_upload_bytes`) and 50 MiB for other formats (`max_upload_bytes`). Set `stoa-chat --max-ifc-upload-mib 1024` to accept IFC models up to 1 GiB. Both limits must be positive byte counts; the CLI accepts a positive whole number of MiB. A larger filename-based size allowance does not bypass content validation. JSON requests are bounded to 1 MiB, questions to 10,000 characters, titles to 200 characters. PDF accepts 1–1000 accessible, unencrypted pages; image pixel limit is 80 million. SVG uses static element and inline presentation-style allowlists and disallows script, events, document declarations, active CSS and external resources. DXF accepts complete ASCII and binary drawings. Original coordinates are retained: raster pixels, PDF points, SVG viewBox including origin, or explicit width/height in user coordinates when no viewBox exists. Absolute SVG length units are converted to CSS pixels at 96 dpi; relative or omitted dimensions remain unresolved rather than inventing a viewport. PNG/JPEG header dimensions are bounded before allocating decoded pixels. IFC GlobalIds and DXF handles are included as `entity_ids`.

Browser Host must be localhost or 127.0.0.1 with the current server port; Origin must be same-origin unless explicitly allowlisted by `allowed_origins`. The default CLI binds only 127.0.0.1. This is a local prototype, with no authentication or remote deployment configuration.

Public HTTP coverage: 31 tests passed on 2026-11-14, including restart, deletion/shared assets, all formats, multipage PDF, question/follow-up/evidence, malformed requests and answers, provider exceptions, unsafe SVG, scope isolation, and frontend path isolation. Controlled analysis tests verify application behavior, not perception accuracy. No provider was called.
