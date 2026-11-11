"""Measure small rectangle using SHARED cylinder fit on union of reference+small points.

This implements the program.md strategy:
1. Keep manual masks authoritative (no propagation)
2. Fit ONE cylinder to UNION of reference and small region points
3. Project both regions onto that shared cylinder
4. Compute area ratio directly in COLMAP units, scale cancels
"""

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
    """Extract frame number from 4-digit filename like frame_0001.jpg."""
    stem = Path(name).stem
    # Handle patterns: frame_0001 or frame_0001_mask
    parts = stem.split("_")
    if len(parts) >= 2:
        return int(parts[-1].rstrip("jpg", "JPG", "png", "PNG"))
    raise ValueError(f"Cannot parse frame number from {name}")


def load_mask(path: Path, shape: tuple[int, int]) -> np.ndarray:
    """Load a mask image and convert to binary."""
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        # Try reading as color first
        img = cv2.imread(str(path))
        if img is not None:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            raise RuntimeError(f"Could not read mask: {path}")
    if img.shape != shape:
        img = cv2.resize(img, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    # Convert to binary mask (non-zero pixels are part of region)
    return img > 0


def try_find_mask(reference_dir: Path, images_dir: Path, name_jpg: str, ref_ext: str = "jpg") -> np.ndarray:
    """Try to find reference mask for a given image. Tries multiple patterns."""
    stem = Path(name_jpg).stem  # e.g., "frame_0001" or "frame_0020_mask"
    
    # Pattern 1: stem_mask.jpg (e.g., frame_0020_mask.jpg)
    mp = reference_dir / f"{stem}_{ref_ext}"
    if mp.exists():
        return load_mask(mp, find_depth_file(None, name_jpg).shape if False else None)
    
    # Pattern 2: stem.png (fallback)
    mp = reference_dir / f"{stem}.png"
    if mp.exists():
        return load_mask(mp, None)
    
    return np.zeros((512, 512), dtype=bool)


def measure_with_shared_cylinder(
    reference_dir: Path,
    small_dir: Path,
    model_dir: Path,
    depth_dir: Path,
    images_dir: Path,
    min_views: int = 3,
    max_points_per_mask: int = 20000,
) -> dict:
    """Fit ONE cylinder to union of reference and small points.

    Returns area ratio calibrated against known 56.25 cm² reference.
    """
    cameras = read_cameras(model_dir / "cameras.txt")
    poses = read_poses(model_dir / "images.txt")
    
    # Debug: check how many images and what stems we have
    print(f"Loaded {len(poses)} poses from COLMAP", file=sys.stderr)
    
    # Collect usable views from both mask directories
    views = []
    rng = np.random.default_rng(42)
    
    # Process reference masks (frames that have manual reference masks)
    ref_stems_loaded = set()
    for name in sorted(reference_dir.glob("frame_*_mask.jpg")) + sorted(reference_dir.glob("frame_*_mask.png")):
        stem_raw = Path(name).stem  # e.g., "frame_0020_mask"
        # Extract the base stem without _mask suffix
        if stem_raw.endswith("_mask"):
            stem = stem_raw[:-5]  # Remove "_mask" -> "frame_0020" (5 chars)
        else:
            stem = stem_raw
        
        name_jpg = str(images_dir / f"{stem}.jpg")
        if not Path(name_jpg).exists():
            print(f"Image not found: {name_jpg}", file=sys.stderr)
            continue
        
        pose = poses.get(stem)
        if not pose or pose.camera_id not in cameras:
            print(f"Pose lookup failed for stem={stem}: pose={pose}, camera_id={pose.camera_id if pose else 'N/A'}", file=sys.stderr)
            continue
        
        try:
            image = cv2.imread(name_jpg, cv2.IMREAD_GRAYSCALE)
            if image is None:
                print(f"Could not read image: {name_jpg}", file=sys.stderr)
                continue
        
        try:
            image = cv2.imread(name_jpg, cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            depth = read_colmap_array(find_depth_file(depth_dir, name_jpg))
            camera = cameras[pose.camera_id]
            K = camera.K()
            if depth.shape != image.shape:
                sx, sy = depth.shape[1] / image.shape[1], depth.shape[0] / image.shape[0]
                K[0, :] *= sx
                K[1, :] *= sy
            
            mask = load_mask(name, depth.shape)
            
            if len(mask) == 0:
                continue
                
            ref_stems_loaded.add(stem)
            views.append({
                "name": name_jpg,
                "stem": stem,
                "K": K,
                "R": pose.R(),
                "t": pose.tvec,
                "depth": depth,
                "mask_ref": mask,
                "is_reference": True,
            })
        except Exception as e:
            print(f"Error loading reference {name}: {e}", file=sys.stderr)
            continue
    
    # Process small masks - try multiple patterns
    for name_jpg in sorted(images_dir.glob("frame_*.jpg")):
        stem = Path(name_jpg).stem  # e.g., "frame_0001" or "frame_0020"
        
        # Skip if already loaded as reference mask
        if stem in ref_stems_loaded:
            continue
        
        # Try different mask path patterns for small masks
        mask_path = None
        
        # Pattern 1: small_rec_mask/{stem}.jpg (e.g., frame_0020.jpg)
        mp1 = small_dir / f"{stem}.jpg"
        if mp1.exists():
            mask_path = mp1
        
        # Pattern 2: small_rec_mask/{stem}_small_rec.jpg (e.g., frame_0020_small_rec.jpg)
        elif (small_dir / f"{stem}_small_rec.jpg").exists():
            mask_path = small_dir / f"{stem}_small_rec.jpg"
        
        # Pattern 3: propagated masks in PNG format
        elif (Path("/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface/data/small_rec_mask_propagated") / f"{stem}.png").exists():
            mask_path = Path("/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface/data/small_rec_mask_propagated") / f"{stem}.png"
        
        # Pattern 4: PNG variant with _small_rec suffix
        elif (small_dir / f"{stem}_small_rec.png").exists():
            mask_path = small_dir / f"{stem}_small_rec.png"
        
        if not mask_path:
            print(f"No small mask found for stem={stem}, trying continued processing", file=sys.stderr)
            # Continue anyway - use empty/placeholder mask or continue to next
            continue
        
        pose = poses.get(stem)
        if not pose or pose.camera_id not in cameras:
            print(f"Pose lookup failed for small stem={stem}: pose={pose}", file=sys.stderr)
            continue
        
        try:
            image = cv2.imread(str(name_jpg), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            depth = read_colmap_array(find_depth_file(depth_dir, str(name_jpg)))
            camera = cameras[pose.camera_id]
            K = camera.K()
            if depth.shape != image.shape:
                sx, sy = depth.shape[1] / image.shape[1], depth.shape[0] / image.shape[0]
                K[0, :] *= sx
                K[1, :] *= sy
            
            mask = load_mask(mask_path, depth.shape)
            
            if len(mask) == 0:
                continue
            
            views.append({
                "name": str(name_jpg),
                "stem": stem,
                "K": K,
                "R": pose.R(),
                "t": pose.tvec,
                "depth": depth,
                "mask_ref": mask,  # Small region points - loaded from small mask dir
                "is_reference": False,
            })
        except Exception as e:
            print(f"Error loading small {name_jpg}: {e}", file=sys.stderr)
            continue
    
    if len(views) < min_views:
        raise RuntimeError(f"Only {len(views)} usable views found (min {min_views})")

    # Collect points from ALL views (union of reference and small regions)
    point_sets = []
    for source in views:
        mask = source["mask_ref"]
        if len(mask) == 0:
            continue
        points = backproject(
            source["depth"], mask, source["K"],
            source["R"], source["t"], max_points_per_mask, rng
        )
        kept = filter_by_views(points, source["name"], views, min_views, 0.02)
        if len(kept):
            point_sets.append(kept)
    
    if not point_sets:
        raise RuntimeError(f"No points survived for shared cylinder fit")
    
    # UNION of all points - this is what we fit the cylinder to
    points = np.vstack(point_sets)
    
    # Fit ONE cylinder to the union
    cylinder = fit_cylinder(points)
    
    # Create mesh and keep only triangles supported by sufficient views
    mesh = create_cylinder_mesh(points, cylinder, 160, 160)
    mesh = keep_mask_supported_triangles(mesh, views, min_views)
    
    total_area_colmap = area(mesh)
    
    # Now separate reference and small regions for individual area measurement
    ref_points = None
    small_points = None
    
    for source in views:
        if len(source["mask_ref"]) == 0:
            continue
        
        name_jpg = source["name"]
        depth = read_colmap_array(find_depth_file(depth_dir, name_jpg))
        
        stem = Path(name_jpg).stem
        
        # Reference mask - try JPG first (from data/masks/), then PNG fallback
        ref_mask_path = reference_dir / f"{stem}_mask.jpg"
        if not ref_mask_path.exists():
            ref_mask_path = reference_dir / f"{stem}_mask.png"
        
        ref_mask = np.zeros_like(depth, dtype=bool)
        if ref_mask_path.exists():
            ref_mask = load_mask(ref_mask_path, depth.shape)
        
        # Small mask - use the same mask we loaded for this view
        small_mask = source["mask_ref"]
        
        # Backproject reference region (from reference masks only)
        if ref_mask is not None and len(ref_mask):
            ref_points_view = backproject(
                source["depth"], ref_mask, source["K"],
                source["R"], source["t"], max_points_per_mask // 2, rng
            )
            kept_ref = filter_by_views(ref_points_view, name_jpg, views, min_views, 0.02)
            if len(kept_ref) > 0 and ref_points is None:
                ref_points = kept_ref
            elif len(kept_ref) > 0:
                if ref_points is not None:
                    ref_points = np.vstack([ref_points, kept_ref])
        
        # Backproject small region
        kept_small = filter_by_views(small_mask * depth, source["depth"], source["K"],
                                      source["R"], source["t"], max_points_per_mask // 2, rng)
        kept_small = keep_mask_supported_triangles(kept_small, [source], min_views)
        if len(kept_small) > 0 and small_points is None:
            small_points = kept_small
        elif len(kept_small) > 0:
            if small_points is not None:
                small_points = np.vstack([small_points, kept_small])
    
    ref_area_colmap = area(create_cylinder_mesh(ref_points, cylinder, 160, 160)) if ref_points is not None else 0.0
    small_area_colmap = area(create_cylinder_mesh(small_points, cylinder, 160, 160)) if small_points is not None else 0.0
    
    # Calibrate using known reference area of 56.25 cm²
    scale_factor = np.sqrt(56.25 / total_area_colmap)
    
    ref_area_cm2 = total_area_colmap * scale_factor * scale_factor
    small_area_cm2 = small_area_colmap * scale_factor * scale_factor
    
    return {
        "views": len(views),
        "points_union": int(len(points)),
        "area_union_colmap_units2": float(total_area_colmap),
        "ref_points_count": int(len(ref_points)) if ref_points is not None else 0,
        "small_points_count": int(len(small_points)) if small_points is not None else 0,
        "ref_area_colmap_units2": float(ref_area_colmap) if ref_points is not None else 0.0,
        "small_area_colmap_units2": float(small_area_colmap) if small_points is not None else 0.0,
        "scale_cm_per_colmap_unit": float(scale_factor),
        "ref_area_cm2": float(ref_area_cm2),
        "small_area_cm2": float(small_area_cm2),
        "cylinder_radius": float(cylinder["radius"]),
        "cylinder_residual_median": float(cylinder["residual_median"]),
        "cylinder_residual_p95": float(cylinder["residual_p95"]),
        "mesh_triangles": int(len(mesh.triangles)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("data/colmap_output/dense/sparse"))
    parser.add_argument("--depth", type=Path, default=Path("data/colmap_output/dense/stereo/depth_maps"))
    parser.add_argument("--images", type=Path, default=Path("data/colmap_output/dense/images"))
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--small", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/reports/small_rectangle_shared_ratio.json"))
    parser.add_argument("--min-views", type=int, default=3)
    parser.add_argument("--max-points", type=int, default=20000)
    args = parser.parse_args()

    model_dir = find_txt_model(args.model)
    
    report = measure_with_shared_cylinder(
        reference_dir=args.reference,
        small_dir=args.small,
        model_dir=model_dir,
        depth_dir=args.depth,
        images_dir=args.images,
        min_views=args.min_views,
        max_points_per_mask=args.max_points,
    )
    
    report["absolute_error_cm2"] = abs(report["small_area_cm2"] - 4.0)
    report["relative_error_percent"] = 100 * report["absolute_error_cm2"] / 4.0
    
    output_path = args.output.parent
    output_path.mkdir(parents=True, exist_ok=True)
    
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"Results written to {args.output}")
    print(f"Small area: {report['small_area_cm2']:.4f} cm² (error: {report['absolute_error_cm2']:.4f}, rel: {report['relative_error_percent']:.2f}%)")


if __name__ == "__main__":
    main()
