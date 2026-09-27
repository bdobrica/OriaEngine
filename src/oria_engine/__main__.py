"""Supported local HTTP entrypoint (make api)."""

import sys

import uvicorn

from oria_engine.app import create_app
from oria_engine.config import ConfigurationError


def main() -> None:
    try:
        app = create_app()
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    uvicorn.run(app, host="127.0.0.1", port=8001, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
