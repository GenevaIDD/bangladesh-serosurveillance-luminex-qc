"""Top-level entry point for PyInstaller and direct execution."""

import multiprocessing

from src.main import main

if __name__ == "__main__":
    # Required so a PyInstaller-frozen build handles any multiprocessing worker
    # bootstrap correctly instead of re-launching the whole app. Must be the
    # first thing called. (Curve fitting also runs serially when frozen; this is
    # belt-and-suspenders.)
    multiprocessing.freeze_support()
    main()
