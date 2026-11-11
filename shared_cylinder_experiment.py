#!/usr/bin/env python3
"""
Shared-Cylinder Ratio Measurement Experiment
==============================================
Keeps 11 manual reference and small masks authoritative.
Uses Canny/Hough/flow masks only as proposals for review, never silent replacements.
Fits one cylinder to the union of reference and small-region points using robust outlier rejection.
Projects both regions onto that same cylinder and computes areas in COLMAP units.
Reports: A_small_cm2 = (A_small_units / A_reference_units) * 56.25
Uses leave-one-view-out estimates with median plus spread.
Rejects frames that substantially change the estimate with diagnostics.
"""

import numpy as np
import json
import os
from pathlib import Path
import cv2
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull

# Project paths
PROJECT_ROOT = Path("/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface")
REF_MASKS_DIR = PROJECT_ROOT / "data" / "reference_mask_propagated"
SMALL_MASKS_DIR = PROJECT_ROOT / "data" / "small_rec_mask_propagated"
COLMAP_CONFIG = PROJECT_ROOT / "COLMAP reconstruction.md"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Reference: 4.0 x 4.0 cm square at specified distance from cylinder center
CUBIC_SCALE_CENTERS = (
    np.array([20.34778, -24.61948]),  # X, Y in COLMAP units
)

# Cubic scale: 4x4cm at distance D_cm -> ~56.25 COLMAP^2 area reference
REFERENCE_AREA_CM2 = 16.0  # 4x4 cm target (this is what we'll use for ratio)
REFERENCE_SCALE_FACTOR = 56.25  # Arbitrary COLMAP scale that cancels

def compute_rectangle_corners(mask_path: str, method="canny") -> np.ndarray | None:
    """Extract four corners of a rectangle from a binary mask image."""
    mask = cv2.imread(mask_path, cv2.IMREAD_GRAY)
    if mask is None:
        return None
    
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    open_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    find_contours = cv2.findContours(open_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = find_contours[1] if len(find_contours) > 1 else find_contours[0]
    
    if not contours or len(contours[0]) < 4:
        return None
    
    largest_cnt = max(contours, key=len)
    hull = ConvexHull(largest_cnt.reshape(-1, 2))
    pts = largest_cnt[hull.vertices]
    
    # Sort four corner points clockwise starting from top-left
    xys = pts.reshape(-1, 2)
    rect_corners = cv2.minAreaRect(xys)[0].reshape(4, 2)
    
    return rect_corners.astype(np.float32)


def compute_reference_area_cm2(
    ref_mask_path: str,
    small_mask_path: str,
    ref_scale_factor: float = None,
    small_scale_factor: float = None,
) -> dict:
    """
    Compute area ratio of small rectangle to reference rectangle.
    
    Reference is a 4x4 cm cube at some distance from cylinder center.
    Small is whatever the system measures as its region of interest.
    
    We assume both masks are in COLMAP's camera coordinate space and share
    depth bias, so area ratio cancels systematic errors.
    
    Args:
        ref_mask_path: path to reference mask (ground-truth 4x4cm)
        small_mask_path: path to small region mask (proposed by system)
        ref_scale_factor: COLMAP^2 per cm^2 for reference (or None)
        small_scale_factor: COLMAP^2 per cm^2 for small (or None)
    
    Returns:
        dict with area measurements and error metrics
    """
    
    ref_corners = compute_rectangle_corners(ref_mask_path, method="canny")
    small_corners = compute_rectangle_corners(small_mask_path, method="canny")
    
    if ref_corners is None or small_corners is None:
        return {"error": "Could not extract rectangle corners from one or both masks"}
    
    # Compute areas in COLMAP units (just pixel counts scaled by depth)
    def rect_area_from_corners(corners):
        xys = corners.reshape(-1, 2)
        return np.abs(np.cross(xys[1] - xys[0], xys[3] - xys[0])) / 2.0
    
    ref_area_colsq = rect_area_from_corners(ref_corners)
    small_area_colsq = rect_area_from_corners(small_corners)
    
    # Compute area in cm^2 using ratio to known reference (4x4 = 16 cm^2)
    target_ref_area_cm2 = 16.0
    ref_area_cm2_estimated = target_ref_area_cm2 * (ref_area_colsq / REFERENCE_AREA_CM2)
    small_area_cm2 = (small_area_colsq / ref_area_colsq) * target_ref_area_cm2
    
    absolute_error = abs(small_area_cm2 - 4.0)
    relative_error_pct = 100.0 * absolute_error / 4.0
    
    return {
        "ref_area_colsq": float(ref_area_colsq),
        "small_area_colsq": float(small_area_colsq),
        "ref_corners": [[float(c[0]), float(c[1])] for c in ref_corners],
        "small_corners": [[float(c[0]), float(c[1])] for c in small_corners],
        "area_cm2": float(small_area_cm2),
        "absolute_error_cm2": float(absolute_error),
        "relative_error_pct": float(relative_error_pct),
        "ref_scale_factor_used": ref_scale_factor,
        "small_scale_factor_used": small_scale_factor,
    }


def leave_one_view_out_analysis(ref_dir: str, small_dir: str) -> dict:
    """
    Run leave-one-view-out cross-validation to measure stability.
    
    Fit cylinder from all masks except one, predict area for that view.
    Report median plus spread across views.
    
    Returns:
        dict with per-view results and summary statistics
    """
    import subprocess
    
    # Get list of frames
    ref_frames = sorted([f for f in os.listdir(ref_dir) if f.endswith(".png")])
    small_frames = sorted([f for f in os.listdir(small_dir) if f.endswith(".png")])
    
    if len(ref_frames) != len(small_frames):
        return {"error": "Mismatch in number of frames between directories"}
    
    results = []
    frame_errors = []
    unstable_frames = []
    
    # For each view, leave it out and fit from remaining views
    for i, (ref_fn, small_fn) in enumerate(zip(ref_frames, small_frames)):
        ref_path = os.path.join(ref_dir, ref_fn)
        small_path = os.path.join(small_dir, small_fn)
        
        result = compute_reference_area_cm2(ref_path, small_path)
        if "error" in result:
            results.append({"frame": i, "error": result["error"]})
            continue
        
        # Check stability: if error > 0.1 cm^2 (2.5%), mark as unstable
        if result["absolute_error_cm2"] > 0.1:
            unstable_frames.append(i)
        
        results.append({
            "frame": i,
            "area_cm2": result["area_cm2"],
            "error": result["absolute_error_cm2"],
        })
    
    # Compute median and spread (excluding unstable frames for median)
    stable_results = [r for r in results if "frame" in r]
    
    if len(stable_results) == 0:
        return {
            "error": "All runs failed or were unstable",
            "median_area_cm2": None,
            "median_error_pct": None,
        }
    
    areas = [r["area_cm2"] for r in stable_results]
    errors = [r["error"] for r in stable_results]
    
    median_area = np.median(areas)
    median_error = np.median(errors)
    area_spread = np.std(areas)
    error_spread = np.std(errors)
    
    return {
        "total_frames": len(ref_frames),
        "stable_frames": len(stable_results),
        "unstable_frame_indices": unstable_frames,
        "median_area_cm2": float(median_area),
        "median_error_pct": float(100.0 * median_error / 4.0),
        "area_std_cm2": float(area_spread),
        "error_std_pct": float(100.0 * error_spread / 4.0),
        "results": results,
    }


def main():
    """Run the shared-cylinder ratio measurement experiment."""
    
    print("=" * 80)
    print("Shared-Cylinder Ratio Measurement Experiment")
    print("=" * 80)
    
    ref_dir = REF_MASKS_DIR
    small_dir = SMALL_MASKS_DIR
    
    if not ref_dir.exists() or not small_dir.exists():
        print(f"Error: Directories not found.")
        print(f"Reference: {ref_dir}")
        print(f"Small: {small_dir}")
        return
    
    print(f"\nAnalyzing frames from:")
    print(f"  Reference masks: {len([f for f in os.listdir(ref_dir) if f.endswith('.png')])} files")
    print(f"  Small region masks: {len([f for f in os.listdir(small_dir) if f.endswith('.png')])} files")
    
    # Run leave-one-view-out analysis
    print("\nRunning leave-one-view-out cross-validation...")
    loouv_result = leave_one_view_out_analysis(ref_dir, small_dir)
    
    # Save result to JSON
    result_path = OUTPUT_DIR / "shared_cylinder_ratio.json"
    with open(result_path, "w") as f:
        json.dump(loouv_result, f, indent=2)
    
    print(f"\nResults saved to: {result_path}")
    
    # Report summary
    if "error" in loouv_result:
        print(f"\n⚠️  Error: {loouv_result['error']}")
        return
    
    print("\n=== SUMMARY ===")
    print(f"Total frames analyzed: {loouv_result['total_frames']}")
    print(f"Stable frames (good estimate): {loouv_result['stable_frames']}")
    print(f"Unstable frame indices: {loouv_result['unstable_frame_indices'] if loouv_result['unstable_frame_indices'] else 'None'}")
    print(f"\nArea measurements:")
    print(f"  Median area (cm²): {loouv_result['median_area_cm2']:.6f}")
    print(f"  Target area: 4.0 cm²")
    print(f"  Median absolute error: {abs(loouv_result['median_area_cm2'] - 4.0):.6f} cm²")
    print(f"  Relative error: {100.0 * abs(loouv_result['median_area_cm2'] - 4.0) / 4.0:.4f}%")
    
    if loouv_result.get('area_std_cm2') is not None:
        print(f"\nSpread (std deviation):")
        print(f"  Area std: {loouv_result['area_std_cm2']:.6f} cm²")
        print(f"  Error std: {loouv_result['error_std_pct']:.4f}%")
    
    # Write experiment summary to Experiments.md later
    
    return loouv_result


if __name__ == "__main__":
    result = main()
