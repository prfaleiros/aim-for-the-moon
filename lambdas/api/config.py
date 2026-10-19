import json
import pathlib

_cache = None


def load_config() -> dict:
    """config.json is bundled into the Lambda package; cached per cold start."""
    global _cache
    if _cache is None:
        here = pathlib.Path(__file__).parent
        for p in (here / "config.json", here.parent.parent / "config" / "config.json"):
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8"))
                _cache = {k: v for k, v in raw.items() if not k.startswith("_")}
                break
        else:
            raise FileNotFoundError("config.json not found")
    return _cache
