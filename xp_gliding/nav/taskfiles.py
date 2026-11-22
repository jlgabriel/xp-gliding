"""The Flight Computer's task files: SeeYou CUP files (`cup.py`) and PLN soaring tasks, MSFS
flight plans that hold a task (`pln.py`), told apart by their extension. Both read to a `cup.CupFile`, so a
task is loaded, kept and flown the same way whatever its file.

Pure Python: no `xp`, nothing of the engine.
"""

import os

from . import cup, pln


def find_files(folder):
    """The task files in a folder, by name, sorted without regard to case."""
    return cup.find_files(folder, cup.TASK_EXTENSIONS)


def load(path):
    """A task file to its CupFile, read by its extension. Raises OSError if it cannot be read."""
    if os.path.splitext(path)[1].lower() == ".pln":
        return pln.load(path)
    return cup.load(path)
