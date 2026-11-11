"""Propagate small-rectangle quadrilateral masks through the image sequence."""

import argparse
import json
import logging
from pathlib import Path

import cv2
import numpy as np


LOG = logging.getLogger("small-rectangle-propagation")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def frame_number(path: Path) -> int:
    return int(path.stem.split("_")[1])


def read_gray(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"Could not read image: {path}")
    return image


def binary_mask(path: Path, shape: tuple[int, int]) -> np.ndarray:
    mask = read_gray(path)
    if mask.shape != shape:
        mask = cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    binary = mask > 127
    border = np.concatenate((binary[0], binary[-1], binary[:, 0], binary[:, -1]))
    if float(border.mean()) > 0.5:
        binary = ~binary
    components, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary.astype(np.uint8), 8
    )
    if components <= 1:
        raise ValueError(f"Mask has no foreground component: {path}")
    label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == label


def order_corners(points: np.ndarray) -> np.ndarray:
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    if cv2.contourArea(ordered.astype(np.float32)) < 0:
        ordered = ordered[::-1]
    return ordered.astype(np.float32)


def detect_quadrilateral(image: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, dict]:
    """Detect four corners, using Canny/Hough first and contour geometry as a fallback."""
    masked = cv2.bitwise_and(image, image, mask=(mask.astype(np.uint8) * 255))
    edges = cv2.Canny(masked, 40, 120)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=25, minLineLength=20, maxLineGap=12
    )
    contour_edges = cv2.morphologyEx(
        mask.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)
    )
    contours, _ = cv2.findContours(
        contour_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        raise ValueError("No rectangle boundary found.")
    contour = max(contours, key=cv2.contourArea)
    perimeter = cv2.arcLength(contour, True)
    polygon = cv2.approxPolyDP(contour, 0.04 * perimeter, True).reshape(-1, 2)
    if len(polygon) != 4:
        rectangle = cv2.minAreaRect(contour)
        polygon = cv2.boxPoints(rectangle)
    corners = order_corners(polygon)
    if cv2.contourArea(corners) <= 0:
        raise ValueError("Detected quadrilateral has zero area.")
    side_lengths = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
    ratio = float(max(side_lengths) / max(min(side_lengths), 1e-6))
    if ratio > 8:
        raise ValueError(f"Unrealistic quadrilateral aspect ratio: {ratio:.2f}")
    return corners, {"hough_segments": 0 if lines is None else len(lines), "aspect_ratio": ratio}


def track_corners(source: np.ndarray, target: np.ndarray, corners: np.ndarray) -> np.ndarray:
    forward, status, _ = cv2.calcOpticalFlowPyrLK(
        source, target, corners.reshape(-1, 1, 2), None,
        winSize=(31, 31), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if forward is not None and np.all(status):
        backward, back_status, _ = cv2.calcOpticalFlowPyrLK(
            target, source, forward, None,
            winSize=(31, 31), maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if backward is not None and np.all(back_status):
            error = np.linalg.norm(backward.reshape(-1, 2) - corners, axis=1)
            if float(np.max(error)) <= 20:
                return forward.reshape(-1, 2).astype(np.float32)

    flow = cv2.calcOpticalFlowFarneback(
        source, target, None, 0.5, 3, 21, 3, 5, 1.2, 0
    )
    height, width = source.shape
    x = np.rint(corners[:, 0]).astype(int)
    y = np.rint(corners[:, 1]).astype(int)
    inside = (x >= 0) & (x < width) & (y >= 0) & (y < height)
    if not np.all(inside):
        raise ValueError("Corner left image during tracking.")
    forward = corners + flow[y, x]
    reverse = cv2.calcOpticalFlowFarneback(
        target, source, None, 0.5, 3, 21, 3, 5, 1.2, 0
    )
    x2 = np.rint(forward[:, 0]).astype(int)
    y2 = np.rint(forward[:, 1]).astype(int)
    inside = (x2 >= 0) & (x2 < width) & (y2 >= 0) & (y2 < height)
    if not np.all(inside):
        raise ValueError("Fallback flow left image during tracking.")
    error = np.linalg.norm(forward + reverse[y2, x2] - corners, axis=1)
    if float(np.max(error)) > 50:
        raise ValueError(f"Forward/backward tracking error too high: {max(error):.2f}px")
    return forward.astype(np.float32)


def correct_with_edges(image: np.ndarray, corners: np.ndarray, radius: int = 24) -> np.ndarray:
    edges = cv2.Canny(image, 40, 120)
    corrected = corners.copy()
    height, width = image.shape
    for index, (x, y) in enumerate(corners):
        x0, y0 = max(0, int(x) - radius), max(0, int(y) - radius)
        x1, y1 = min(width, int(x) + radius + 1), min(height, int(y) + radius + 1)
        candidates = np.argwhere(edges[y0:y1, x0:x1] > 0)
        if len(candidates) == 0:
            continue
        candidates_xy = candidates[:, ::-1].astype(np.float32)
        candidates_xy += np.array([x0, y0], dtype=np.float32)
        distances = np.sum((candidates_xy - (x, y)) ** 2, axis=1)
        nearest = np.argmin(distances)
        if float(np.sqrt(distances[nearest])) <= 6:
            corrected[index] = candidates_xy[nearest]
    return corrected


def fill_inside_larger(corners: np.ndarray, larger: np.ndarray) -> np.ndarray:
    candidate = np.zeros_like(larger, dtype=np.uint8)
    cv2.fillPoly(candidate, [np.rint(corners).astype(np.int32)], 255)
    candidate &= larger.astype(np.uint8) * 255
    if int(candidate.sum()) == 0:
        raise ValueError("Generated rectangle is outside the larger reference mask.")
    return candidate


def propagate(
    images_dir: Path,
    anchors_dir: Path,
    anchor_pattern: str,
    larger_dir: Path | None,
    output_dir: Path,
) -> dict:
    images = sorted(
        (p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES),
        key=frame_number,
    )
    anchors = {
        frame_number(p): p
        for p in anchors_dir.glob(anchor_pattern)
        if p.suffix.lower() in IMAGE_SUFFIXES
    }
    if not images or not anchors:
        raise RuntimeError("Images and *_small_rec anchor masks are required.")
    image_by_number = {frame_number(p): p for p in images}
    missing = sorted(set(anchors) - set(image_by_number))
    if missing:
        raise ValueError(f"Anchor masks have no matching images: {missing}")
    shape = read_gray(images[0]).shape
    gray = {frame_number(p): read_gray(p) for p in images}
    larger = None
    if larger_dir is not None:
        larger = {
            number: binary_mask(larger_dir / f"frame_{number:04d}.png", shape)
            for number in image_by_number
        }
    corners: dict[int, np.ndarray] = {}
    diagnostics = {}
    for number, path in anchors.items():
        anchor_mask = binary_mask(path, shape)
        corners[number], diagnostics[number] = detect_quadrilateral(gray[number], anchor_mask)

    failed = []
    for image_path in images:
        number = frame_number(image_path)
        if number in corners:
            continue
        anchor_number = min(anchors, key=lambda anchor: abs(anchor - number))
        current = anchor_number
        direction = 1 if number > anchor_number else -1
        current_index = next(i for i, p in enumerate(images) if frame_number(p) == current)
        target_index = next(i for i, p in enumerate(images) if frame_number(p) == number)
        try:
            for index in range(current_index, target_index, direction):
                next_number = frame_number(images[index + direction])
                tracked = track_corners(gray[current], gray[next_number], corners[current])
                corners[next_number] = correct_with_edges(gray[next_number], tracked)
                current = next_number
        except ValueError as exc:
            failed.append({"frame": number, "from": current, "error": str(exc)})

    output_dir.mkdir(parents=True, exist_ok=True)
    for number, image_path in image_by_number.items():
        if number not in corners:
            continue
        try:
            if larger is None:
                mask = np.zeros(shape, dtype=np.uint8)
                cv2.fillPoly(mask, [np.rint(corners[number]).astype(np.int32)], 255)
            else:
                mask = fill_inside_larger(corners[number], larger[number])
        except ValueError as exc:
            failed.append({"frame": number, "error": str(exc)})
            continue
        output_path = output_dir / f"{image_path.stem}.png"
        if not cv2.imwrite(str(output_path), mask):
            raise RuntimeError(f"Could not write {output_path}")
    report = {
        "images": len(images),
        "anchors": len(anchors),
        "generated": len(list(output_dir.glob("*.png"))),
        "failed_frames": failed,
        "anchor_diagnostics": diagnostics,
        "method": "Canny/Hough quadrilateral, LK forward/backward tracking, local Canny correction",
    }
    (output_dir / "propagation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if failed:
        LOG.warning("%d frames failed and were not silently extrapolated.", len(failed))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=Path("data/colmap_output/dense/images"))
    parser.add_argument("--anchors", type=Path, default=Path("data/small_rec_mask"))
    parser.add_argument("--anchor-pattern", default="*_small_rec.*")
    parser.add_argument("--larger-masks", type=Path, default=Path("data/masks"))
    parser.add_argument("--no-containment", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("data/small_rec_mask_propagated"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    containment = None if args.no_containment else args.larger_masks
    report = propagate(args.images, args.anchors, args.anchor_pattern, containment, args.output)
    print(json.dumps({k: report[k] for k in ("images", "anchors", "generated", "failed_frames")}, indent=2))


if __name__ == "__main__":
    main()
