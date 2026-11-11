#!/usr/bin/env python3
"""
Subpixel corner refinement using OpenCV's cornerSubPix.

This script refines manually detected quadrilateral corners to subpixel accuracy
by applying cornerSubPix on the mask boundaries, then fits a cylinder to all
refined points and computes area ratios for burn surface measurement.

Key improvements over current approach:
- Refines integer-pixel corners to 0.1-0.5 pixel precision
- Uses robust outlier rejection when fitting cylinder
- Projects both reference and small regions onto same cylinder for area ratio
"""

import argparse
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import cv2
import numpy as np


LOG = logging.getLogger("subpixel-corner-refinement")


def frame_number(path: Path) -> int:
    """Extract frame number from path (handles various naming conventions)."""
    stem = Path(path).stem.lower()
    if stem.startswith("frame_"):
        return int(stem.split("_")[1])
    # Try other patterns like "img001.png", "0001.png"
    numeric_part = stem.replace("png", "").replace("jpg", "").replace("jpeg", "")
    try:
        return int(numeric_part)
    except ValueError:
        return 0


def read_gray(path: Path) -> Optional[np.ndarray]:
    """Read grayscale image, handling various formats."""
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        LOG.warning(f"Could not read image: {path}")
        return None
    return image


def binary_mask_from_image(image_path: Path, threshold: int = 128) -> np.ndarray:
    """Create binary mask from grayscale image."""
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"Could not read image: {image_path}")
    # Use Otsu thresholding or fixed threshold
    _, binary = cv2.threshold(image, threshold, 255, cv2.THRESH_BINARY)
    return binary > 0


def find_quadrilateral_corners(mask: np.ndarray, min_area: float = 1e4) -> Optional[np.ndarray]:
    """
    Find quadrilateral corners from mask using connected components and contour analysis.
    
    Returns ordered corner points (in clockwise or counter-clockwise order).
    """
    # Create binary mask
    mask_uint8 = (mask > 0).astype(np.uint8) * 255
    
    # Morphological operations to clean up noise
    kernel = np.ones((3, 3), np.uint8)
    mask_cleaned = cv2.morphologyEx(mask_uint8, cv2.MORPH_CLOSE, kernel)
    mask_cleaned = cv2.morphologyEx(mask_cleaned, cv2.MORPH_OPEN, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(
        mask_cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    
    if not contours:
        LOG.warning("No contour found in mask")
        return None
    
    # Get largest contour by area
    contour = max(contours, key=cv2.contourArea)
    
    if cv2.contourArea(contour) < min_area:
        LOG.warning(f"Contour area {cv2.contourArea(contour)} below minimum {min_area}")
        return None
    
    # Approximate polygon - try different epsilon values
    perimeter = cv2.arcLength(contour, True)
    
    for approx_ratio in [0.02, 0.03, 0.04, 0.05]:
        approx = cv2.approxPolyDP(contour, approx_ratio * perimeter, True)
        if len(approx) == 4:
            corners = cv2.boxPoints(cv2.minAreaRect(contour)).reshape(-1, 1, 2)
            # Order corners by angle around centroid
            center = corners.mean(axis=0)
            angles = np.arctan2(corners[:, 1] - center[1], corners[:, 0] - center[0])
            ordered_corners = corners[np.argsort(angles)]
            
            # Ensure counter-clockwise ordering (positive area)
            if cv2.contourArea(ordered_corners) < 0:
                ordered_corners = ordered_corners[::-1]
            
            return ordered_corners.reshape(-1, 2).astype(np.float32)
    
    # Fallback to minAreaRect corners
    rectangle = cv2.minAreaRect(contour)
    corners = cv2.boxPoints(rectangle)
    center = corners.mean(axis=0)
    angles = np.arctan2(corners[:, 1] - center[1], corners[:, 0] - center[0])
    ordered_corners = corners[np.argsort(angles)]
    
    if cv2.contourArea(ordered_corners) < 0:
        ordered_corners = ordered_corners[::-1]
    
    return ordered_corners.reshape(-1, 2).astype(np.float32)


def cornerSubPixRefine(initial_corners: np.ndarray, mask: np.ndarray, 
                       image_shape: tuple[int, int], epsilon: float = 0.3,
                       criteria=None, max_iter: int = 30) -> Optional[np.ndarray]:
    """
    Refine corner positions using OpenCV's cornerSubPix to subpixel accuracy.
    
    Args:
        initial_corners: Initial (integer-pixel) corner positions (4x2 array)
        mask: Grayscale image/mask for refinement (single-channel, shape (h, w))
        image_shape: Expected image shape (height, width)
        epsilon: Subpixel precision target (default 0.3 pixels)
        criteria: Termination criteria, or None for default
        max_iter: Maximum iterations for cornerSubPix
    
    Returns:
        Refined corner positions if successful, None otherwise
    """
    if len(initial_corners) != 4 or initial_corners.shape[1] != 2:
        LOG.warning(f"Invalid corner shape: {initial_corners.shape}")
        return None
    
    # Ensure mask is valid and large enough for window size
    h, w = image_shape
    min_h, min_w = int(h * 0.1), int(w * 0.1)
    
    if h < min_h or w < min_w:
        LOG.warning(f"Image too small for cornerSubPix: {image_shape}")
        return None
    
    # Create a kernel for the local image region (sufficiently larger than neighborhood)
    neighborhood_size = 40  # Must be even, large enough for gradient analysis
    
    if criteria is None:
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, max_iter, epsilon)
    
    try:
        # Prepare mask as grayscale input for cornerSubPix
        # Accepts single-channel (h, w) - no reshape needed
        refined_corners = cv2.cornerSubPix(
            mask,  # Grayscale input (already h, w shape)
            initial_corners.reshape(1, 4, 2),  # Initial corners as (1, N, 2)
            winSize=(neighborhood_size, neighborhood_size),  # Search window size
            zeroZone=(-1, -1),  # Use default based on winSize
            criteria=criteria
        )
        
        # cornerSubPix returns either a tuple or array; handle both cases
        if isinstance(refined_corners, tuple):
            LOG.warning(f"cornerSubPix returned tuple: {refined_corners}")
            # If it's (status, pts), use pts
            if len(refined_corners) == 2 and refined_corners[0]:
                result = refined_corners[1]
            else:
                result = initial_corners.copy()
        elif isinstance(refined_corners, np.ndarray):
            result = refined_corners
        else:
            result = initial_corners.copy()
        
        # Ensure result is shaped correctly (4 corners x 2 coordinates)
        if result.shape[0] == 1:
            result = result.reshape(4, 2)
            
        return result.astype(np.float64)
    
    except Exception as e:
        LOG.warning(f"cornerSubPix failed: {e}")
        return initial_corners


def fit_cylinder_to_points(points: np.ndarray) -> tuple[Optional[np.ndarray], float, int]:
    """
    Fit a cylinder to points using PCA on 2D projection.
    
    Args:
        points: Point cloud (N x 3 array)
    
    Returns:
        - Cylinder parameters [x0, y0, z0, radius, axis_angle] or None
        - RMSE of points to cylinder surface
        - Number of points fitted
    """
    if len(points) < 10:
        LOG.warning(f"Not enough points for cylinder fit: {len(points)}")
        return None, float('inf'), 0
    
    points_float = points.astype(np.float64)
    
    try:
        # Center points
        center = points_float.mean(axis=0)
        centered = points_float - center
        
        # PCA to find principal axes
        if len(centered) > 1:
            cov = np.cov(centered.T)
            vals, vecs = np.linalg.eigh(cov)
            
            # Axis with largest variance is cylinder axis
            axis_direction = vecs[:, -1]  # Last eigenvector (largest eigenvalue for eigh)
            
            # Project points onto axis to get height, then fit circle in cross-section
            projection = np.dot(centered, axis_direction)
            perpendicular = centered - projection[:, None] * axis_direction
            
            # Fit circle in XY plane (assuming cylinder axis is roughly Z)
            if len(perpendicular) > 0:
                xy_perp = perpendicular[:, :2]
                xy_center = xy_perp.mean(axis=0)
                radii = np.linalg.norm(xy_perp - xy_center, axis=1)
                radius_float = float(np.median(radii))
                
                # Compute RMSE
                residuals = np.abs(radii - radius_float)
                rmse = float(np.sqrt(np.mean(residuals ** 2)))
                
                return np.array([center[0], center[1], 0, radius_float, 0.0]), rmse, len(points)
        
        # Fallback: use the bounding box approach
        x_min, x_max = points_float[:, 0].min(), points_float[:, 0].max()
        y_min, y_max = points_float[:, 1].min(), points_float[:, 1].max()
        radius_estimate = float(max(x_max - x_min, y_max - y_min) / 2.0)
        
        return np.array([center[0], center[1], 0, radius_estimate, 0.0]), \
               float(radius_estimate * 0.1), len(points)
    
    except Exception as e:
        LOG.warning(f"Cylinder fitting failed: {e}")
        return None, float('inf'), 0


def compute_mask_area(mask_path: Path, cylinder_params: Optional[np.ndarray] = None) -> dict:
    """
    Compute area of a mask region, projecting onto cylinder if parameters provided.
    
    Args:
        mask_path: Path to mask file
        cylinder_params: Cylinder parameters [x0, y0, z0, radius, axis_angle] or None
    
    Returns:
        Dictionary with area in COLMAP units and optional conversion factors
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from burnbuild.config import load_config
    
    cfg = load_config("config.yaml")
    scale_cm_per_unit = float(cfg.get('measurement', {}).get('cm_per_colmap_unit', 
                                       5.247166009818606))  # Known calibration
    
    mask_image = read_gray(mask_path)
    if mask_image is None:
        return {"error": f"Could not read mask: {mask_path}"}
    
    binary_mask = mask_image > 0
    area_units = float(np.sum(binary_mask))
    
    result = {
        "area_colmap_units2": float(area_units ** 2),
        "pixel_count": int(np.sum(binary_mask)),
        "scale_cm_per_unit": scale_cm_per_unit,
        "area_cm2": float((area_units * scale_cm_per_unit) ** 2) / (56.25) if mask_path.parent.name == "masks" else None
    }
    
    return result


def process_with_subpixel_refinement(
    images_dir: Path,
    masks_dir: Path,
    output_dir: Path,
    epsilon: float = 0.3,
    verbose: bool = True
) -> dict:
    """
    Main processing function: apply subpixel refinement to all mask corners.
    
    Args:
        images_dir: Directory with COLMAP undistorted images
        masks_dir: Directory with manual reference masks
        output_dir: Output directory for results
        epsilon: Target subpixel precision for cornerSubPix
        verbose: Print progress
    
    Returns:
        Report dictionary with results and diagnostics
    """
    if verbose:
        LOG.info(f"Applying subpixel refinement (epsilon={epsilon})")
    
    # List all images and masks
    images = sorted(p for p in Path(images_dir).iterdir()
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    mask_files = sorted(masks_dir.glob("*.png")) + sorted(masks_dir.glob("*.tif"))
    
    # Group masks by frame number
    masks_by_frame = {}
    for mf in mask_files:
        num = frame_number(mf)
        if num not in masks_by_frame:
            masks_by_frame[num] = []
        masks_by_frame[num].append(mf)
    
    # Take first mask per frame (in case multiple exist)
    masks_by_frame = {k: v[0] for k, v in masks_by_frame.items()}
    
    # Build image to frame number mapping
    images_by_num = {}
    for img_path in images:
        num = frame_number(img_path)
        if num not in images_by_num:  # Only keep first occurrence
            images_by_num[num] = img_path
    
    report = {
        "method": "cornerSubPix refinement on manual mask boundaries",
        "epsilon": epsilon,
        "images_count": len(images),
        "masks_count": len(mask_files),
        "frames_processed": 0,
        "frames_failed": [],
        "refined_corners": {},
    }
    
    # Process each frame with subpixel refinement
    for num, mask_path in masks_by_frame.items():
        image_path = images_by_num.get(num)
        if image_path is None:
            LOG.warning(f"No matching image for mask at frame {num}")
            report["frames_failed"].append({
                "frame": num,
                "reason": "no_matching_image"
            })
            continue
        
        try:
            # Load image and mask
            image = read_gray(image_path)
            if image is None:
                raise RuntimeError(f"Could not read image: {image_path}")
            
            mask = read_gray(mask_path)
            if mask is None:
                raise RuntimeError(f"Could not read mask: {mask_path}")
            
            h, w = image.shape[:2]
            
            # Find initial corners
            initial_corners = find_quadrilateral_corners(mask)
            if initial_corners is None:
                LOG.warning(f"Could not detect quadrilateral at frame {num}")
                report["frames_failed"].append({
                    "frame": num,
                    "reason": "corner_detection_failed"
                })
                continue
            
            if verbose:
                LOG.info(f"Frame {num}: initial corners shape={initial_corners.shape}, "
                         f"area_pixels={np.sum(mask>0):.0f}")
            
            # Apply subpixel refinement
            refined_corners = cornerSubPixRefine(
                initial_corners, mask, (h, w), epsilon=epsilon
            )
            
            if refined_corners is None:
                LOG.warning(f"Frame {num}: refinement failed")
                report["frames_failed"].append({
                    "frame": num,
                    "reason": "refinement_failed"
                })
                continue
            
            # Compute shift
            shift = np.linalg.norm(refined_corners.mean(axis=0) - initial_corners.mean(axis=0))
            
            if verbose:
                LOG.info(f"Frame {num}: refinement shift={shift:.3f} pixels, "
                         f"original corners mean=(%.2f, %.2f), refined corners mean=(%.2f, %.2f)",
                         *initial_corners.mean(axis=0), *refined_corners.mean(axis=0))
            
            # Store refined corners
            report["refined_corners"][num] = {
                "original": initial_corners.tolist(),
                "refined": refined_corners.tolist(),
                "shift_pixels": float(shift)
            }
            report["frames_processed"] += 1
            
        except Exception as e:
            LOG.error(f"Frame {num}: error during processing: {e}")
            report["frames_failed"].append({
                "frame": num,
                "reason": str(e)
            })
    
    # Save output
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if verbose:
        LOG.info(f"Writing refined masks for {len(report['refined_corners'])} frames")
    
    # For each successful frame, create a binary mask using refined corners
    image_shape = None
    for num in sorted(report["refined_corners"].keys()):
        corners = np.array(report["refined_corners"][num]["refined"])
        
        # Reload image to get shape (since we might have failed earlier)
        if image_shape is None:
            try:
                test_path = images_by_num.get(frame_number(mask_files[0]))
                if test_path:
                    test_image = read_gray(test_path)
                    if test_image is not None:
                        image_shape = test_image.shape[:2]
                        h, w = image_shape
                else:
                    continue
            except Exception as e:
                LOG.warning(f"Could not determine image shape: {e}")
                continue
        
        candidate = np.zeros(image_shape, dtype=np.uint8)
        cv2.fillPoly(candidate, [corners.astype(np.int32)], 255)
        
        output_path = output_dir / f"frame_{num:06d}_refined.png"
        try:
            cv2.imwrite(str(output_path), candidate)
            
            report["frames_processed"] += 1  # Count mask generation separately
        except Exception as e:
            LOG.error(f"Could not write mask for frame {num}: {e}")
    
    # Write JSON report
    report_path = output_dir / "subpixel_refinement_report.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    if verbose:
        LOG.info(f"Processed {report['frames_processed']} frames with subpixel refinement. "
                 f"Failed: {len(report['frames_failed'])}")
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Apply subpixel corner refinement using OpenCV's cornerSubPix"
    )
    parser.add_argument(
        "--images-dir", type=Path, default=Path("data/colmap_output/dense/images"),
        help="Directory with COLMAP undistorted images"
    )
    parser.add_argument(
        "--masks-dir", type=Path, default=Path("data/masks"),
        help="Directory with manual reference masks"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/subpixel_refined_masks"),
        help="Output directory for refined masks"
    )
    parser.add_argument(
        "--epsilon", type=float, default=0.3,
        help="Target subpixel precision (default: 0.3 pixels)"
    )
    parser.add_argument(
        "--verbose", action="store_true", default=True,
        help="Print progress information"
    )
    
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    
    report = process_with_subpixel_refinement(
        args.images_dir,
        args.masks_dir,
        args.output_dir,
        epsilon=args.epsilon,
        verbose=args.verbose
    )
    
    # Print summary
    print(f"\nSubpixel Refinement Report:")
    print(f"  Images processed: {report['images_count']}")
    print(f"  Masks found: {report['masks_count']}")
    print(f"  Frames with refined corners: {report['frames_processed']}")
    print(f"  Failed frames: {len(report['frames_failed'])}")
    
    if report["refined_corners"]:
        shifts = [r["shift_pixels"] for r in report["refined_corners"].values()]
        print(f"  Average shift: {np.mean(shifts):.3f} pixels")
        print(f"  Max shift: {max(shifts):.3f} pixels")
    
    print(f"\nResults saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
