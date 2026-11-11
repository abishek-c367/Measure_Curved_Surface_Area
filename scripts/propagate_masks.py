"""Propagate manually annotated masks across an ordered image sequence."""

import argparse
from pathlib import Path

import cv2
import numpy as np


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
MASK_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def frame_number(path: Path) -> int:
    return int(path.stem.rsplit("_", 1)[1])


def load_mask(path: Path, shape: tuple[int, int]) -> np.ndarray:
    mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise RuntimeError(f"Could not read mask: {path}")
    if mask.shape != shape:
        print(f"Resizing {path.name} from {mask.shape} to {shape}.")
        mask = cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    binary = mask > 127
    border = np.concatenate((binary[0], binary[-1], binary[:, 0], binary[:, -1]))
    if border.mean() > 0.5:
        binary = ~binary

    labels_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary.astype(np.uint8), 8
    )
    if labels_count <= 1:
        raise ValueError(f"Mask {path} contains no foreground region.")
    largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    return np.where(labels == largest_label, 255, 0).astype(np.uint8)


def warp_mask(mask: np.ndarray, source: np.ndarray, target: np.ndarray) -> np.ndarray:
    source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    target_gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
    flow = cv2.calcOpticalFlowFarneback(
        source_gray,
        target_gray,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=21,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0,
    )
    height, width = mask.shape
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )
    remapped = cv2.remap(
        mask,
        grid_x - flow[..., 0],
        grid_y - flow[..., 1],
        cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return np.where(remapped > 127, 255, 0).astype(np.uint8)


def propagate_masks(images_dir: Path, masks_dir: Path) -> list[Path]:
    images = sorted(
        (path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES),
        key=frame_number,
    )
    anchors = sorted(
        (
            path
            for path in masks_dir.iterdir()
            if path.suffix.lower() in MASK_SUFFIXES
            and path.stem.endswith("_mask")
        ),
        key=lambda path: frame_number(Path(path.stem.removesuffix("_mask") + path.suffix)),
    )
    if not images:
        raise RuntimeError(f"No images found in {images_dir}")
    if not anchors:
        raise RuntimeError(f"No *_mask reference masks found in {masks_dir}")

    image_by_number = {frame_number(path): path for path in images}
    anchor_by_number = {}
    for anchor in anchors:
        number = frame_number(Path(anchor.stem.removesuffix("_mask") + anchor.suffix))
        if number not in image_by_number:
            raise ValueError(f"Reference mask has no matching image: {anchor.name}")
        anchor_by_number[number] = anchor

    first_image = cv2.imread(str(images[0]))
    if first_image is None:
        raise RuntimeError(f"Could not read image: {images[0]}")
    shape = first_image.shape[:2]
    masks = {
        number: load_mask(path, shape) for number, path in anchor_by_number.items()
    }

    for index, image_path in enumerate(images):
        number = frame_number(image_path)
        if number in masks:
            continue
        anchor_number = min(anchor_by_number, key=lambda anchor: abs(anchor - number))
        current_mask = masks[anchor_number]
        current_index = next(
            i for i, candidate in enumerate(images) if frame_number(candidate) == anchor_number
        )
        target_index = index
        step = 1 if current_index < target_index else -1
        for image_index in range(current_index, target_index, step):
            source = cv2.imread(str(images[image_index]))
            target = cv2.imread(str(images[image_index + step]))
            if source is None or target is None:
                raise RuntimeError(f"Could not read frames around {images[image_index].name}")
            if step == 1:
                current_mask = warp_mask(current_mask, source, target)
            else:
                current_mask = warp_mask(current_mask, target, source)
            masks[frame_number(images[image_index + step])] = current_mask

    output_paths = []
    for image_path in images:
        number = frame_number(image_path)
        output_path = masks_dir / f"{image_path.stem}.png"
        if not cv2.imwrite(str(output_path), masks[number]):
            raise RuntimeError(f"Could not write propagated mask: {output_path}")
        output_paths.append(output_path)
    return output_paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Propagate *_mask reference masks to every image using optical flow."
    )
    parser.add_argument("--images", type=Path, default=Path("data/colmap_output/dense/images"))
    parser.add_argument("--masks", type=Path, default=Path("data/masks"))
    args = parser.parse_args()
    outputs = propagate_masks(args.images, args.masks)
    print(f"Wrote {len(outputs)} masks to {args.masks}")


if __name__ == "__main__":
    main()
