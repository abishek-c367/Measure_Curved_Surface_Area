import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from burnbuild.config import load_config
from burnbuild.masks import validate_masks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--images-only", action="store_true")
    args = parser.parse_args()
    cfg = load_config(args.config)
    source = Path(cfg["paths"]["images_dir"])
    images = [p for p in source.iterdir() if p.suffix.lower() in
              {".jpg", ".jpeg", ".png", ".tif", ".tiff"}]
    print(f"Original images: {len(images)}")
    if not images:
        raise SystemExit(f"No source images in {source}")
    if args.images_only:
        return
    undistorted = Path(cfg["paths"]["dense_dir"]) / "images"
    if not undistorted.exists():
        raise SystemExit("Run `python main.py prepare` before checking masks.")
    result = validate_masks(undistorted, cfg["paths"]["masks_dir"])
    print(result)
    if result["missing"] or result["empty"] or result["mismatched"]:
        raise SystemExit("Mask validation failed.")
    print("Mask validation passed.")


if __name__ == "__main__":
    main()
