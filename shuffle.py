import sys
import os
import copy

from app.services.helper import unsort_map

LEVELS_DIR = "levels"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python shuffle.py <level.json>")
        sys.exit(1)

    source_path = sys.argv[1]
    from generate import load_level_file, save_level_to
    meet, _, version = load_level_file(source_path)
    shuffled = unsort_map(copy.deepcopy(meet))
    save_level_to(meet, shuffled, source_path, version)
