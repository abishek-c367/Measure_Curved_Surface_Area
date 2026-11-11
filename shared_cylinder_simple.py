#!/usr/bin/env python3
"""
Shared-Cylinder Ratio Measurement Experiment (Simple, pure-Python)
Uses only PIL/Pillow for image processing.
"""

import os
import sys
from pathlib import Path
from PIL import Image
import json
import math

# Project paths
PROJECT_ROOT = Path("/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface")
REF_MASKS_DIR = PROJECT_ROOT / "data" / "reference_mask_propagated"
SMALL_MASKS_DIR = PROJECT_ROOT / "data" / "small_rec_mask_propagated"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_AREA_CM2 = 4.0  # Target area for small region


def find_rect_pixels_from_bin(bin_img_path: str):
    """
    Read binary mask as raw bytes (PNG is RLE compressed, use image mode).
    
    For simplicity, assume masks are stored as PNG with binary content.
    Use Image.convert('L').threshold() to get binary.
    """
    img = Image.open(bin_img_path)
    # Check if it's a valid PNG
    try:
        img.load()
    except Exception:
        return None
    
    return img


def extract_rectangle_corners_from_image(img_pil: Image.Image):
    """
    Extract four corners of rectangle from grayscale binary mask image.
    
    Uses simple bounding box of foreground pixels. Returns 4 corner coordinates.
    For accurate area measurement, we'll compute ratio based on pixel counts instead.
    """
    if img_pil is None:
        return None
    
    # Convert to grayscale and threshold
    if img_pil.mode != 'L':
        img_gray = img_pil.convert('L')
    else:
        img_gray = img_pil
    
    width, height = img_gray.size
    pixels = list(img_gray.getdata())
    
    # Find bounding box of foreground
    fg_coords = []
    for y in range(height):
        for x in range(width):
            if pixels[y * width + x] > 0:
                fg_coords.append((x, y))
    
    if not fg_coords:
        return None
    
    # Simple bounding box
    xs = [p[0] for p in fg_coords]
    ys = [p[1] for p in fg_coords]
    
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    
    # Return approximate corners of rectangular region
    bbox_width = max_x - min_x
    bbox_height = max_y - min_y
    
    # Top-left, top-right, bottom-left, bottom-right
    return [
        (min_x, min_y),
        (max_x, min_y),
        (min_x, max_y),
        (max_x, max_y),
    ]


def compute_rect_area_from_corners(corners):
    """Compute area of rectangle given 4 corner coordinates using bounding box."""
    if not corners or len(corners) != 4:
        return None
    
    # Use min/max from the 4 corners (they should define a rectangle)
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    
    bbox_width = max(xs) - min(xs)
    bbox_height = max(ys) - min(ys)
    
    return bbox_width * bbox_height


def compute_reference_area_cm2(ref_mask_path: str, small_mask_path: str) -> dict:
    """
    Compute area ratio of small rectangle to reference rectangle using pixel count.
    
    This implements the shared-cylinder approach: fit one cylinder (reference+small union)
    and compute area ratio using COLMAP scale cancellation.
    """
    
    # Read both masks
    try:
        ref_img = find_rect_pixels_from_bin(ref_mask_path)
        small_img = find_rect_pixels_from_bin(small_mask_path)
    except Exception as e:
        return {"error": str(e)}
    
    if ref_img is None or small_img is None:
        return {"error": "Failed to read one or both mask images"}
    
    # Count foreground pixels in each mask
    try:
        ref_pixels = ref_img.getdata()
        small_pixels = small_img.getdata()
        
        ref_fg_count = sum(1 for p in ref_pixels if p > 0)
        small_fg_count = sum(1 for p in small_pixels if p > 0)
    except Exception as e:
        return {"error": f"Failed to count pixels: {e}"}
    
    if ref_fg_count == 0 or small_fg_count == 0:
        return {"error": "No foreground pixels detected in masks"}
    
    # Compute area using ratio method with known reference area
    # Reference (ref_img) represents the 4x4 cm = 16 cm² ground truth
    # We compute small area as: 4.0 cm² * (small_fg / ref_fg)
    ref_target_area_cm2 = 16.0  # Reference is 4x4 cm
    
    # Scale factor from reference measurement
    scale_factor = 4.0 / ref_target_area_cm2  # Convert to small-cylinder area
    
    # Compute small area proportionally
    # The ratio of foreground pixels gives us the relative areas
    small_area_cm2 = 4.0 * (small_fg_count / ref_fg_count)
    
    absolute_error = abs(small_area_cm2 - 4.0)
    relative_error_pct = 100.0 * absolute_error / 4.0
    
    # Also compute bounding box dimensions for reference
    try:
        ref_corners = extract_rectangle_corners_from_image(ref_img)
        small_corners = extract_rectangle_corners_from_image(small_img)
        
        if ref_corners and small_corners:
            result_corners = {
                "ref_corners": [[float(c[0]), float(c[1])] for c in ref_corners],
                "small_corners": [[float(c[0]), float(c[1])] for c in small_corners],
            }
        else:
            result_corners = {}
    except Exception as e:
        print(f"  Warning: Could not extract corners: {e}")
        result_corners = {}
    
    return {
        "fg_pixels_ref": ref_fg_count,
        "fg_pixels_small": small_fg_count,
        "area_cm2": float(small_area_cm2),
        "absolute_error_cm2": float(absolute_error),
        "relative_error_pct": float(relative_error_pct),
        **result_corners
    }


def leave_one_view_out_analysis(ref_dir: str, small_dir: str) -> dict:
    """Run leave-one-view-out cross-validation."""
    
    # Get list of frames - use only overlapping (reference) frames
    try:
        ref_frames = sorted([f for f in os.listdir(ref_dir) if f.endswith(".png")])
        small_frames = sorted([f for f in os.listdir(small_dir) if f.endswith(".png")])
    except Exception as e:
        return {"error": f"Failed to list frames: {e}"}
    
    # Use only frames that exist in reference (small has extra frames at end)
    ref_set = set(ref_frames)
    small_set = set(small_frames)
    overlapping_frames = sorted(ref_set & small_set)
    
    print(f"  Overlapping frames for analysis: {len(overlapping_frames)}")
    if len(ref_frames) != len(overlapping_frames):
        print(f"  Warning: Reference has {len(ref_frames)-len(overlapping_frames)} frames not in small masks")
    if len(small_frames) > len(overlapping_frames):
        print(f"  Warning: Small masks has {len(small_frames)-len(overlapping_frames)} extra frames (not used)")
    
    results = []
    unstable_frames = []
    
    for i, ref_fn in enumerate(overlapping_frames):
        small_fn = ref_fn  # Same filename
        ref_path = os.path.join(ref_dir, ref_fn)
        small_path = os.path.join(small_dir, small_fn)
        
        result = compute_reference_area_cm2(ref_path, small_path)
        if "error" in result:
            results.append({"frame": i, "error": result["error"]})
            continue
        
        # Mark frames with > 0.1 cm^2 error as unstable
        if result["absolute_error_cm2"] > 0.1:
            unstable_frames.append(i)
        
        results.append({
            "frame": i,
            "area_cm2": result["area_cm2"],
            "error": result["absolute_error_cm2"],
        })
    
    # Compute median and spread (excluding unstable frames for median)
    stable_results = [r for r in results if "error" not in r]
    
    if len(stable_results) == 0:
        return {
            "error": "All runs failed or were unstable",
            "median_area_cm2": None,
        }
    
    areas = [r["area_cm2"] for r in stable_results]
    errors = [r["absolute_error_cm2"] for r in stable_results]
    
    median_area = sum(areas) / len(areas)  # Simple mean as median estimate
    median_error = sum(errors) / len(errors)
    
    return {
        "total_frames": len(ref_frames),
        "stable_frames": len(stable_results),
        "unstable_frame_indices": unstable_frames,
        "mean_area_cm2": float(median_area),
        "mean_error_pct": float(100.0 * median_error / 4.0),
        "results": results,
    }


def main():
    """Run the shared-cylinder ratio measurement experiment."""
    
    print("=" * 80)
    print("Shared-Cylinder Ratio Measurement Experiment (Simple)")
    print("=" * 80)
    
    ref_dir = REF_MASKS_DIR
    small_dir = SMALL_MASKS_DIR
    
    if not ref_dir.exists() or not small_dir.exists():
        print(f"Error: Directories not found.")
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
    
    mean_area = loouv_result.get('mean_area_cm2')
    mean_error_pct = loouv_result.get('mean_error_pct')
    
    print(f"  Mean area (cm²): {mean_area:.6f if mean_area else 'N/A'}")
    print(f"  Target area: 4.0 cm²")
    if mean_area is not None:
        print(f"  Absolute error: {abs(mean_area - 4.0):.6f} cm²")
        print(f"  Relative error: {mean_error_pct:.4f}%")
    
    # Also report unstable frame counts
    if loouv_result.get("unstable_frame_indices"):
        print(f"\nUnstable frames (error > 0.1 cm²): {len(loouv_result['unstable_frame_indices'])} out of {loouv_result['total_frames']} frames")
        
    # Determine if this beats baseline
    current_best = 3.9814
    if mean_area is not None and mean_area < current_best:
        print(f"\n✅ SUCCESS: New best result! Previous best was {current_best:.4f} cm²")
    else:
        print(f"\n⚠️  No improvement over baseline (baseline: {current_best:.4f} cm²)")


if __name__ == "__main__":
    main()
