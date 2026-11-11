from pathlib import Path
import cv2
import numpy as np


def find_mask(folder, image_name):
    folder = Path(folder)
    stem = Path(image_name).stem
    for ext in [".png", ".tif", ".tiff", ".jpg", ".jpeg"]:
        p = folder / f"{stem}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"Missing manual mask for {image_name} in {folder}")


def load_mask(path, shape):
    m = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if m is None:
        raise ValueError(f"Cannot read mask: {path}")
    if m.shape != tuple(shape):
        raise ValueError(f"Mask {path} has shape {m.shape}; expected {shape}. "
                         "Masks must align with COLMAP undistorted images/depth maps.")
    return m > 0


def validate_masks(images_dir, masks_dir):
    images = sorted(p for p in Path(images_dir).iterdir()
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"})
    missing, empty, mismatch = [], [], []
    for image_path in images:
        try:
            mp = find_mask(masks_dir, image_path.name)
        except FileNotFoundError:
            missing.append(image_path.name)
            continue
        im = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        mask = cv2.imread(str(mp), cv2.IMREAD_GRAYSCALE)
        if im is None or mask is None or im.shape != mask.shape:
            mismatch.append(image_path.name)
        elif not np.any(mask > 0):
            empty.append(image_path.name)
    return {"image_count": len(images), "missing": missing,
            "empty": empty, "mismatched": mismatch}
