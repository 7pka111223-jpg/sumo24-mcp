"""Installed-package entry points; compatible with the legacy sibling imports."""
import asyncio
from pathlib import Path
import sys


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from server import main as serve
    asyncio.run(serve())


if __name__ == "__main__":
    main()
