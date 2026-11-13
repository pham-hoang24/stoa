def main() -> None:
    from .cli import main as _main
    raise SystemExit(_main())
