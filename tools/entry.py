"""PyInstaller entry point.

PyInstaller runs its target as ``__main__`` with no package context, so relative
imports inside ``horizon/__main__.py`` would fail. This shim imports the package
normally instead.
"""

import sys

from horizon.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
