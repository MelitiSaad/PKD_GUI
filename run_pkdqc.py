"""Entry point for PyInstaller builds (uses absolute imports).

`python -m pkdqc` is fine for running from source, but PyInstaller needs a plain
script whose imports don't rely on package/relative context — this is it.
"""
import sys

from pkdqc.app import run

if __name__ == "__main__":
    sys.exit(run())
