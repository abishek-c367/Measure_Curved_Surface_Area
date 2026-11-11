"""Measure baseline and propagated small-rectangle masks on existing COLMAP depth."""

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from burnbuild.colmap_io import find_txt_model, read_cameras, read_poses
from burnbuild.cylindrical import create_cylinder_mesh, fit_cylinder
from burnbuild.depth_io import find_depth_file, read_colmap_array
from burnbuild.meshing import area, keep_mask_supported_triangles
from burnbuild.multiview import filter_by_views
from burnbuild.backproject import backproject


def frame_number(name: str) -> int:
    return int(Path(name).stem.split("_")[1])


def load_mask(path: Path, shape: tuple[int, int]) -> np.ndarray:
    mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise RuntimeError(f"Could not read mask: {path}")
    if mask.shape != shape:
        mask = cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return mask > 0


def measure(mask_dir: Path, names: set[str], model_dir: Path, depth_dir: Path,
            images_dir: Path, min_views: int, max_points: int) -> dict:
    cameras = read_cameras(model_dir / "cameras.txt")
    poses = read_poses(model_dir / "images.txt")
    views = []
    rng = np.random.default_rng(42)
    for name, pose in poses.items():
        if name not in names or pose.camera_id not in cameras:
            continue
        image = cv2.imread(str(images_dir / name), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        depth = read_colmap_array(find_depth_file(depth_dir, name))
        camera = cameras[pose.camera_id]
        K = camera.K()
        if depth.shape != image.shape:
            sx, sy = depth.shape[1] / image.shape[1], depth.shape[0] / image.shape[0]
            K[0, :] *= sx
            K[1, :] *= sy
        mask_path = mask_dir / f"{Path(name).stem}.png"
        if not mask_path.exists():
            candidates = sorted(mask_dir.glob(f"{Path(name).stem}_small_rec.*"))
            if not candidates:
                raise FileNotFoundError(f"No mask for {name} in {mask_dir}")
            mask_path = candidates[0]
        mask = load_mask(mask_path, depth.shape)
        views.append({"name": name, "K": K, "R": pose.R(), "t": pose.tvec,
                      "depth": depth, "mask": mask})
    if len(views) < 3:
        raise RuntimeError(f"Only {len(views)} usable views found in {mask_dir}")

    point_sets = []
    for source in views:
        points = backproject(source["depth"], source["mask"], source["K"],
                             source["R"], source["t"], max_points, rng)
        kept = filter_by_views(points, source["name"], views, min_views, 0.02)
        if len(kept):
            point_sets.append(kept)
    if not point_sets:
        raise RuntimeError(f"No points survived for {mask_dir}")
    points = np.vstack(point_sets)
    cylinder = fit_cylinder(points)
    mesh = create_cylinder_mesh(points, cylinder, 160, 160)
    mesh = keep_mask_supported_triangles(mesh, views, min_views)
    return {
        "views": len(views),
        "points": int(len(points)),
        "area_colmap_units2": area(mesh),
        "cylinder_radius": cylinder["radius"],
        "cylinder_residual_median": cylinder["residual_median"],
        "cylinder_residual_p95": cylinder["residual_p95"],
        "mesh_triangles": int(len(mesh.triangles)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("data/colmap_output/dense/sparse"))
    parser.add_argument("--depth", type=Path, default=Path("data/colmap_output/dense/stereo/depth_maps"))
    parser.add_argument("--images", type=Path, default=Path("data/colmap_output/dense/images"))
    parser.add_argument("--reference", type=Path, default=Path("data/reference_mask_propagated"))
    parser.add_argument("--propagated", type=Path, default=Path("data/small_rec_mask_propagated"))
    parser.add_argument("--output", type=Path, default=Path("outputs/reports/small_rectangle_accuracy.json"))
    parser.add_argument("--max-points", type=int, default=20000)
    parser.add_argument("--propagated-min-views", type=int, default=50)
    args = parser.parse_args()

    model_dir = find_txt_model(args.model)
    all_names = {p.name for p in args.images.iterdir() if p.suffix.lower() == ".jpg"}
    propagated_names = {
        p.name.replace(".png", ".jpg")
        for p in args.propagated.glob("frame_*.png")
        if p.name != "propagation_report.json"
    }
    reference_names = {
        p.name.replace(".png", ".jpg")
        for p in args.reference.glob("frame_*.png")
    }
    reference = measure(args.reference, reference_names, model_dir, args.depth,
                        args.images, args.propagated_min_views, args.max_points)
    small = measure(args.propagated, propagated_names, model_dir, args.depth,
                    args.images, args.propagated_min_views, args.max_points)
    scale = float(np.sqrt(56.25 / reference["area_colmap_units2"]))
    reference["area_cm2"] = reference["area_colmap_units2"] * scale * scale
    small["scale_cm_per_colmap_unit"] = scale
    small["area_cm2"] = small["area_colmap_units2"] * scale * scale
    small["absolute_error_cm2"] = abs(small["area_cm2"] - 4.0)
    small["relative_error_percent"] = 100 * small["absolute_error_cm2"] / 4.0
    report = {
        "true_area_cm2": 4.0,
        "reference": reference,
        "small_rectangle": small,
        "reference_area_calibration_cm2": 56.25,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
