import runpy
import sys
from pathlib import Path

from watchfiles import DefaultFilter, run_process

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
ASSETS = ROOT / "assets"


class CodeAndFrames(DefaultFilter):
    def __call__(self, change, path):
        return path.endswith((".py", ".png")) and super().__call__(change, path)


def run_renderer():
    sys.path.insert(0, str(SRC))
    runpy.run_path(str(SRC / "renderer.py"), run_name="__main__")

if __name__ == "__main__":
    run_process(SRC, ASSETS, target=run_renderer, watch_filter=CodeAndFrames())
