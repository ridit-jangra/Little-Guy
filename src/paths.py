import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys._MEIPASS)
else:
    ROOT = Path(__file__).resolve().parent.parent

ASSETS = ROOT / "assets"
TEMPLATES = ROOT / "templates"
