import json
from pathlib import Path

_PARAMS = json.loads((Path(__file__).parent / "models.json").read_text())

def params(section: str) -> dict:
    return _PARAMS[section]

def norm_surface(surface) -> str:
    s = (surface or "Hard").strip().lower()
    if s.startswith("clay"): return "Clay"
    if s.startswith("grass"): return "Grass"
    return "Hard"          # hard, carpet, indoor, unknown
