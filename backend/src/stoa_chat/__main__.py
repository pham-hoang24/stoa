"""Run the local drawing chat server without benchmark or provider access."""
import argparse
from pathlib import Path

from . import create_server
from stoa.project import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', type=Path, default=ROOT / '.cache' / 'chat')
    parser.add_argument('--port', type=int, default=8092)
    parser.add_argument('--frontend', type=Path, default=ROOT / 'frontend')
    args = parser.parse_args()
    server = create_server(args.storage, port=args.port, static_dir=args.frontend)
    print(f'Drawing chat: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
