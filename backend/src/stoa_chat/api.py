"""Persistent loopback HTTP boundary, independent of benchmark inference."""
import json
import hashlib
import os
import mimetypes
import sqlite3
import sys
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote
from .ingest import inspect_upload
from .answers import abstain, validate_answer

MIB = 1024 * 1024
DEFAULT_UPLOAD_BYTES = 50 * MIB
DEFAULT_IFC_UPLOAD_BYTES = 512 * MIB


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets = self.root / 'assets'
        self.assets.mkdir(exist_ok=True)
        self.native_previews = self.root / 'native_previews'
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / 'chats.sqlite3', check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.commit()
        self.cleanup_assets()

    def cleanup_assets(self):
        referenced = {d['sha256'] for row in self.db.execute('SELECT data FROM chats')
                      for d in json.loads(row[0])['drawings']}
        for asset in self.assets.iterdir():
            if asset.is_file() and asset.name not in referenced:
                asset.unlink(missing_ok=True)
        if self.native_previews.is_dir():
            import shutil
            for cached in self.native_previews.iterdir():
                if cached.name.split('-v')[0] not in referenced:
                    shutil.rmtree(cached, ignore_errors=True)

    def get(self, chat_id):
        row = self.db.execute('SELECT data FROM chats WHERE id=?', (chat_id,)).fetchone()
        if not row:
            raise ApiError(404, 'Chat not found')
        return json.loads(row[0])

    def save(self, chat):
        self.db.execute('INSERT OR REPLACE INTO chats VALUES (?,?)', (chat['id'], json.dumps(chat)))
        self.db.commit()


def create_server(root, host='127.0.0.1', port=8092, answerer=None, max_upload_bytes=DEFAULT_UPLOAD_BYTES, allowed_origins=(), static_dir=None, max_ifc_upload_bytes=DEFAULT_IFC_UPLOAD_BYTES, landing_dir=None):
    """Create a local server; the caller owns serve_forever/shutdown/server_close."""
    upload_limits = {'default': max_upload_bytes, 'ifc': max_ifc_upload_bytes}
    if any(type(limit) is not int or limit <= 0 for limit in upload_limits.values()):
        raise ValueError('Upload limits must be positive byte counts')
    store = Store(root)
    if answerer is None:
        from .analysis import HybridAnswerer
        answerer = HybridAnswerer()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, *args):
            pass

        def respond(self, status, value):
            body = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def read_body(self, limit):
            if self.headers.get('Transfer-Encoding'):
                raise ApiError(400, 'Transfer-Encoding is not supported')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise ApiError(400, 'Invalid Content-Length')
            if length < 0:
                raise ApiError(400, 'Invalid Content-Length')
            if length > limit:
                raise ApiError(413, 'Request exceeds the size limit')
            return self.rfile.read(length)

        def read_json(self):
            try:
                data = json.loads(self.read_body(1024 * 1024) or b'{}')
            except (ValueError, UnicodeError):
                raise ApiError(400, 'Expected a JSON object')
            if not isinstance(data, dict):
                raise ApiError(400, 'Expected a JSON object')
            return data

        def dispatch(self):
            try:
                origin = self.headers.get('Origin')
                local_origins = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
                if origin and origin not in local_origins | set(allowed_origins):
                    raise ApiError(403, 'Browser origin is not allowed')
                host_header = self.headers.get('Host', '')
                if host_header not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
                    raise ApiError(403, 'Host is not allowed')
                self.route()
            except ApiError as exc:
                self.respond(exc.status, {'error': exc.message})
            except (OSError, sqlite3.Error):
                self.respond(500, {'error': 'Local storage is unavailable; please retry'})
            except Exception:
                traceback.print_exc(file=sys.stderr)
                try:
                    self.respond(500, {'error': 'Internal server error'})
                except OSError:
                    pass

        def route(self):
            parts = unquote(urlsplit(self.path).path).strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['api', 'chats'] and parts[3] == 'questions' and self.command == 'POST':
                return self.ask(parts[2])
            if len(parts) in {5, 6} and parts[:2] == ['api', 'chats'] and parts[3] == 'previews' and self.command == 'GET':
                return self.preview(parts)
            with store.lock:
                return self.locked_route()

        def ask(self, chat_id):
            # The lock covers store access only, never the (slow) answerer call.
            with store.lock:
                store.get(chat_id)
            data = self.read_json()
            question = data.get('question')
            with store.lock:
                chat = store.get(chat_id)
                selection = data.get('drawing_ids', chat['selected_drawing_ids'])
                if not isinstance(question, str) or not question.strip() or len(question) > 10000:
                    raise ApiError(400, 'A nonempty question is required')
                if not isinstance(selection, list) or not selection or any(not isinstance(i, str) or i not in [d['id'] for d in chat['drawings']] for i in selection) or len(selection) != len(set(selection)):
                    raise ApiError(400, 'Select drawings belonging to this chat')
                context = {'question': question, 'drawing_ids': selection, 'messages': chat['messages'][:],
                           'drawings': [{**d, 'path': store.assets / d['sha256']} for d in chat['drawings'] if d['id'] in selection]}
                chat['selected_drawing_ids'] = selection
                user_message = {'id': uuid.uuid4().hex, 'role': 'user', 'question': question, 'drawing_ids': selection}
                chat['messages'].append(user_message)
                store.save(chat)
            try:
                answer = answerer(context) if answerer else abstain('Analysis service is not configured')
            except Exception:
                answer = abstain('Analysis failed; please retry', 'analysis_error')
            try:
                answer = validate_answer(answer, context['drawings'])
            except ValueError:
                answer = abstain('Analysis returned invalid or unresolvable evidence', 'invalid_analysis')
            from .native_preview import attach
            answer = attach(answer, context['drawings'], store.native_previews)
            message = {'id': uuid.uuid4().hex, 'role': 'assistant', 'drawing_ids': selection, 'answer': answer}
            for index, evidence in enumerate(answer.get('evidence', [])):
                evidence['url'] = '/api/chats/' + chat_id + '/evidence/' + message['id'] + '/' + str(index)
            with store.lock:
                chat = store.get(chat_id)  # 404 if the chat was deleted meanwhile; never resurrected
                ids = [m['id'] for m in chat['messages']]
                if user_message['id'] not in ids:
                    raise ApiError(404, 'Chat not found')
                # Place the answer right after its own question so concurrent questions stay paired.
                chat['messages'].insert(ids.index(user_message['id']) + 1, message)
                store.save(chat)
            return self.respond(200, message)

        def preview(self, parts):
            # Lazy IFC/DXF plan geometry runs without the store lock (it can take
            # seconds); assets are immutable and content-addressed.
            with store.lock:
                chat = store.get(parts[2])
                drawing = next((d for d in chat['drawings'] if d['id'] == parts[4]), None)
                if drawing is None:
                    raise ApiError(404, 'Drawing not in this chat')
                drawing = {**drawing, 'path': store.assets / drawing['sha256']}
            from . import native_preview
            if len(parts) == 5:
                # Plan index for native sources: pages, entity boxes, or why not.
                result = native_preview.plan(drawing, store.native_previews)
                return self.respond(202 if result['status'] == 'pending' else 200, result)
            try:
                if drawing['format'] in {'ifc', 'dxf'}:
                    body = native_preview.page_png(drawing, int(parts[5]), store.native_previews)
                else:
                    from .render import preview
                    with store.lock:  # raster previews keep their original locking
                        body, _ = preview(drawing, int(parts[5]))
            except (ValueError, RuntimeError):
                raise ApiError(404, 'Preview unavailable')
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def locked_route(self):
            path = unquote(urlsplit(self.path).path)
            if static_dir is not None and self.command == 'GET' and not path.startswith('/api/'):
                # Built landing page owns `/`; the chat app is at `/chat` and keeps its root-level assets.
                landing = Path(landing_dir).resolve() if landing_dir is not None and (Path(landing_dir) / 'index.html').is_file() else None
                if path in ('/chat', '/chat/'):
                    path = '/index.html'
                    roots = [Path(static_dir).resolve()]
                else:
                    roots = [Path(static_dir).resolve()] + ([landing] if landing else [])
                    if landing and path in ('', '/'):
                        roots.reverse()
                target = None
                for root in roots:
                    candidate = (root / (path.lstrip('/') or 'index.html')).resolve()
                    if candidate.is_relative_to(root) and candidate.is_file():
                        target = candidate
                        break
                if target is None:
                    raise ApiError(404, 'Frontend asset not found')
                body = target.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', mimetypes.guess_type(target)[0] or 'application/octet-stream')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-src 'self' blob:; base-uri 'none'")
                self.end_headers()
                self.wfile.write(body)
                return
            parts = path.strip('/').split('/')
            if parts == ['api', 'config'] and self.command == 'GET':
                return self.respond(200, {'upload_limits': upload_limits})
            if parts == ['api', 'chats']:
                if self.command == 'POST':
                    data = self.read_json()
                    if not isinstance(data.get('title', ''), str) or len(data.get('title', '')) > 200:
                        raise ApiError(400, 'Title must be text up to 200 characters')
                    chat = {'id': uuid.uuid4().hex, 'title': data.get('title', 'New chat'),
                            'drawings': [], 'selected_drawing_ids': [], 'messages': []}
                    store.save(chat)
                    return self.respond(201, chat)
                if self.command == 'GET':
                    return self.respond(200, [json.loads(r[0]) for r in store.db.execute('SELECT data FROM chats ORDER BY rowid DESC')])
            if len(parts) == 3 and parts[:2] == ['api', 'chats']:
                chat = store.get(parts[2])
                if self.command == 'GET':
                    return self.respond(200, chat)
                if self.command == 'DELETE':
                    store.db.execute('DELETE FROM chats WHERE id=?', (parts[2],))
                    store.db.commit()
                    store.cleanup_assets()
                    return self.respond(200, {'deleted': chat['id']})
            if len(parts) >= 4 and parts[:2] == ['api', 'chats']:
                chat = store.get(parts[2])
                base = '/api/chats/' + chat['id']
                if parts[3] == 'uploads' and len(parts) == 4 and self.command == 'POST':
                    filename = parse_qs(urlsplit(self.path).query).get('filename', [''])[0]
                    limit = upload_limits['ifc' if Path(filename).suffix.lower() == '.ifc' else 'default']
                    content = self.read_body(limit)
                    try:
                        metadata = inspect_upload(filename, content)
                    except ValueError as exc:
                        raise ApiError(400, str(exc)) from exc
                    digest = hashlib.sha256(content).hexdigest()
                    target = store.assets / digest
                    if not target.exists():
                        temporary = store.assets / (digest + '.' + uuid.uuid4().hex)
                        temporary.write_bytes(content)
                        os.replace(temporary, target)
                    drawing = {'id': uuid.uuid4().hex, 'filename': Path(filename).name, 'sha256': digest, **metadata}
                    drawing['asset_url'] = base + '/assets/' + drawing['id']
                    chat['drawings'].append(drawing)
                    store.save(chat)
                    return self.respond(201, drawing)
                if parts[3] == 'assets' and len(parts) == 5 and self.command == 'GET':
                    drawing = next((d for d in chat['drawings'] if d['id'] == parts[4]), None)
                    if drawing is None:
                        raise ApiError(404, 'Drawing not in this chat')
                    body = (store.assets / drawing['sha256']).read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', drawing['media_type'])
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Content-Security-Policy', "default-src 'none'; sandbox")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if parts[3] == 'evidence' and len(parts) == 6 and self.command == 'GET':
                    for message in chat['messages']:
                        if message['id'] == parts[4] and message['role'] == 'assistant':
                            try:
                                index = int(parts[5])
                                if index < 0:
                                    raise ValueError()
                                return self.respond(200, message['answer']['evidence'][index])
                            except (ValueError, IndexError, KeyError):
                                break
                    raise ApiError(404, 'Evidence not found in this chat')
            raise ApiError(404, 'Endpoint not found')

        do_GET = do_POST = do_DELETE = dispatch

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def server_close(self):
            super().server_close()
            store.db.close()

    return Server((host, port), Handler)
