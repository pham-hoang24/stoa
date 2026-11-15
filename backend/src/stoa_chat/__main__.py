"""Run the local drawing chat app with native facts and configured extraction."""
import argparse
import os
import math
from pathlib import Path

from . import create_server
from .api import DEFAULT_IFC_UPLOAD_BYTES, MIB
from stoa.project import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', type=Path, default=ROOT / '.cache' / 'chat')
    parser.add_argument('--port', type=int, default=8092)
    parser.add_argument('--frontend', type=Path, default=ROOT / 'frontend')
    parser.add_argument('--landing', type=Path, default=ROOT / 'web' / 'dist',
                        help='built landing page served at / when it exists (cd web && pnpm build); chat is then at /chat')
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
    if args.llm_provider:
        os.environ['STOA_LLM_PROVIDER'] = args.llm_provider
    if args.llm_fallback:
        os.environ['STOA_LLM_FALLBACK'] = args.llm_fallback
    if args.llm_timeout_seconds is not None:
        if not math.isfinite(args.llm_timeout_seconds) or args.llm_timeout_seconds <= 0:
            parser.error('--llm-timeout-seconds must be positive and finite')
        os.environ['STOA_LLM_TIMEOUT_SECONDS'] = str(args.llm_timeout_seconds)
    server = create_server(args.storage, port=args.port, static_dir=args.frontend, landing_dir=args.landing,
                           max_ifc_upload_bytes=args.max_ifc_upload_mib * MIB)
    print(f'Drawing chat: http://127.0.0.1:{server.server_port}/chat', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
