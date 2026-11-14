"""Run the local drawing chat app with native facts and configured extraction."""
import argparse
from pathlib import Path

from . import create_server
from .api import DEFAULT_IFC_UPLOAD_BYTES, MIB
from stoa.project import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', type=Path, default=ROOT / '.cache' / 'chat')
    parser.add_argument('--port', type=int, default=8092)
    parser.add_argument('--frontend', type=Path, default=ROOT / 'frontend')
    parser.add_argument('--max-ifc-upload-mib', type=int, default=DEFAULT_IFC_UPLOAD_BYTES // MIB,
                        help='maximum IFC upload size in MiB (default: %(default)s)')
    args = parser.parse_args()
    if args.max_ifc_upload_mib <= 0:
        parser.error('--max-ifc-upload-mib must be positive')
    server = create_server(args.storage, port=args.port, static_dir=args.frontend,
                           max_ifc_upload_bytes=args.max_ifc_upload_mib * MIB)
    print(f'Drawing chat: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
