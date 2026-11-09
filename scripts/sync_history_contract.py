"""Vendor only the public history schema/fixtures from an explicit provider checkout."""

import argparse
import shutil
from pathlib import Path

FILES = ("conversation-history-v1.schema.json", "conversation-history-v1.examples.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / "contracts/second-context"
    for name in FILES:
        source = args.source / "docs/contracts" / name
        target = destination / name
        if args.check:
            if source.read_bytes() != target.read_bytes():
                raise SystemExit(f"History contract drift: {name}")
        else:
            shutil.copyfile(source, target)


if __name__ == "__main__":
    main()
