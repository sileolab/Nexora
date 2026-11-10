"""CLI wrapper forwarding to nexora.cli."""

import sys
from pathlib import Path

root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from nexora.cli import main

if __name__ == "__main__":
    main()
