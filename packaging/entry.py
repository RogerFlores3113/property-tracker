"""PyInstaller entry point (a script, not `-m prophelper`)."""
import multiprocessing

from prophelper.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
