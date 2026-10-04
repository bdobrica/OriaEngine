"""Supported local HTTP entrypoint (make api)."""

import argparse
import sys

import uvicorn

from oria_engine.app import create_app
from oria_engine.config import ConfigurationError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    args = parser.parse_args(argv)
    try:
        app = create_app()
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    uvicorn.run(app, host=args.host, port=8001, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
