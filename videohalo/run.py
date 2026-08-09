"""Backward-compatible module entry point for the VideoHALO 3.7 CLI."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
