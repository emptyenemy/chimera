"""Inspect all routes at native minimum and narrow widths using isolated UI fixtures."""

import argparse
from pathlib import Path

from smoke_autosave import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path)
    main(layout=True, screenshot=parser.parse_args().screenshot)
