from pathlib import Path
import yaml


def load_config(path):
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    root = path.parent
    cfg["_root"] = str(root)
    for key, value in cfg["paths"].items():
        p = Path(value)
        cfg["paths"][key] = str(p if p.is_absolute() else root / p)
    return cfg
