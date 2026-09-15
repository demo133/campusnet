"""允许 `python -m campusnet ...`。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
