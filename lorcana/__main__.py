"""Run the app: python3 -m lorcana"""

import argparse
from pathlib import Path

from .server import serve

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m lorcana", description="Run the Lorcana tournament app.")
    parser.add_argument("--port", type=int, default=8000, help="port to use (default 8000)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR, help="folder for saved tournaments")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    args = parser.parse_args()
    serve(args.data, args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
