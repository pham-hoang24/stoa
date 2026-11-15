"""Run the local drawing chat app with native facts and configured extraction."""
import argparse
import os
import math
from pathlib import Path

from . import create_server
from .api import DEFAULT_IFC_UPLOAD_BYTES, MIB, _hostname
from stoa.project import ROOT


def _env_port(default=8092):
    raw = os.environ.get('PORT')
    if raw is None or raw == '':
        return default
    try:
        port = int(raw)
    except ValueError:
        raise SystemExit(f'PORT must be an integer, got {raw!r}') from None
    if not 1 <= port <= 65535:
        raise SystemExit(f'PORT must be between 1 and 65535, got {port}')
    return port


def _public_hosts(explicit):
    hosts = list(explicit)
    render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip()
    if render_host:
        hosts.append(render_host)
    for item in os.environ.get('STOA_ALLOWED_HOSTS', '').split(','):
        item = item.strip()
        if item:
            hosts.append(item)
    # Preserve order while dropping duplicates / empties.
    seen, unique = set(), []
    for host in hosts:
        if host and host not in seen:
            seen.add(host)
            unique.append(host)
    return unique


def _origins_for_hosts(hosts):
    origins = []
    for host in hosts:
        name = _hostname(host)
        origins.append(f'https://{name}')
        origins.append(f'http://{name}')
    return origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', type=Path, default=ROOT / '.cache' / 'chat')
    parser.add_argument('--host', default='127.0.0.1',
                        help='bind address (default: 127.0.0.1; use 0.0.0.0 for Render)')
    parser.add_argument('--port', type=int, default=_env_port(),
                        help='listen port (default: PORT env, else 8092)')
    parser.add_argument('--frontend', type=Path, default=ROOT / 'frontend')
    parser.add_argument('--landing', type=Path, default=ROOT / 'web' / 'dist',
                        help='built landing page served at / when it exists (cd web && pnpm build); chat is then at /chat')
    parser.add_argument('--allowed-host', action='append', default=[],
                        help='extra Host header value to accept (repeatable); RENDER_EXTERNAL_HOSTNAME is included automatically')
    parser.add_argument('--llm-provider', choices=('nvidia', 'featherless', 'modal'),
                        help='override STOA_LLM_PROVIDER for this server process')
    parser.add_argument('--llm-fallback', choices=('featherless', 'modal', 'none'),
                        help='NVIDIA timeout fallback; overrides STOA_LLM_FALLBACK (default: modal)')
    parser.add_argument('--llm-timeout-seconds', type=float,
                        help='per-provider timeout; overrides STOA_LLM_TIMEOUT_SECONDS (default: 60)')
    parser.add_argument('--max-ifc-upload-mib', type=int, default=DEFAULT_IFC_UPLOAD_BYTES // MIB,
                        help='maximum IFC upload size in MiB (default: %(default)s)')
    args = parser.parse_args()
    if args.max_ifc_upload_mib <= 0:
        parser.error('--max-ifc-upload-mib must be positive')
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if args.llm_provider:
        os.environ['STOA_LLM_PROVIDER'] = args.llm_provider
    if args.llm_fallback:
        os.environ['STOA_LLM_FALLBACK'] = args.llm_fallback
    if args.llm_timeout_seconds is not None:
        if not math.isfinite(args.llm_timeout_seconds) or args.llm_timeout_seconds <= 0:
            parser.error('--llm-timeout-seconds must be positive and finite')
        os.environ['STOA_LLM_TIMEOUT_SECONDS'] = str(args.llm_timeout_seconds)
    allowed_hosts = _public_hosts(args.allowed_host)
    server = create_server(
        args.storage,
        host=args.host,
        port=args.port,
        static_dir=args.frontend,
        landing_dir=args.landing,
        max_ifc_upload_bytes=args.max_ifc_upload_mib * MIB,
        allowed_hosts=allowed_hosts,
        allowed_origins=_origins_for_hosts(allowed_hosts),
    )
    display = '127.0.0.1' if args.host in ('127.0.0.1', 'localhost', '::1') else args.host
    print(f'Drawing chat: http://{display}:{server.server_port}/chat', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
