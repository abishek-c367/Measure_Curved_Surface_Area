#!/usr/bin/env python3
"""
Shared-Cylinder Ratio Measurement Experiment (using OpenCV, no PIL)
Uses cv2 to read PNG masks and count foreground pixels.
"""

import os
import sys
sys.path.insert(0, '.')

try:
    import cv2
except ImportError:
    print("ERROR: OpenCV not found in venv!")
    sys.exit(1)

import json


def parse_png_and_count_fg(filepath):
    """
    Use cv2 to read PNG and count foreground pixels.
    Returns dict with width, height, fg_pixels, total_pixels, or error.
    """
    try:
        # cv2.IMREAD_GRAYSCALE loads as 0-255 grayscale
        img = cv2.imread(filepath, cv2.IMREAD_GRAYSCALE)
        
        if img is None:
            return {"error": f"cv2.imread returned None for {filepath}"}
        
        height, width = img.shape
        total_pixels = width * height
        
        # Count foreground pixels (value > 0)
        fg_count = cv2.countNonZero(img)
        
        return {
            "width": width,
            "height": height,
            "total_pixels": total_pixels,
            "fg_pixels": fg_count,
        }
    except Exception as e:
        return {"error": f"Failed to process image: {e}"}


def compute_area_ratio(ref_path, small_path):
    """Compute area ratio between small and reference masks using CV2."""
    
    ref_parsed = parse_png_and_count_fg(ref_path)
    small_parsed = parse_png_and_count_fg(small_path)
    
    if "error" in ref_parsed:
        return {"error": f"Ref parse error: {ref_parsed['error']}"}
    if "error" in small_parsed:
        return {"error": f"Small parse error: {small_parsed['error']}"}
    
    # Reference represents 7.5x7.5 cm = 56.25 cm² (reference area from baseline results)
    ref_fg_count = ref_parsed["fg_pixels"]
    total_ref = ref_parsed["total_pixels"]
    
    small_fg_count = small_parsed["fg_pixels"]
    total_small = small_parsed["total_pixels"]
    REF_AREA_CM2 = 56.25
    
    # Compute small area proportionally based on pixel counts relative to reference
    if ref_fg_count == 0 or total_ref == 0:
        return {"error": "Reference image has zero foreground or is empty"}
    
    # Area ratio = (small_fg / total_small) / (ref_fg / total_ref) * REF_AREA_CM2
    small_area_cm2 = (small_fg_count / total_small) / (ref_fg_count / total_ref) * REF_AREA_CM2
    
    absolute_error = abs(small_area_cm2 - REF_AREA_CM2)
    relative_error_pct = 100.0 * absolute_error / REF_AREA_CM2
    
    return {
        "fg_pixels_ref": ref_fg_count,
        "total_pixels_ref": total_ref,
        "fg_pixels_small": small_fg_count,
        "total_pixels_small": total_small,
        "area_cm2": float(small_area_cm2),
        "absolute_error_cm2": float(absolute_error),
        "relative_error_pct": float(relative_error_pct),
    }


def leave_one_view_out_analysis(ref_dir: str, small_dir: str) -> dict:
    """Run leave-one-view-out cross-validation."""
    
    # List frames
    try:
        ref_frames = sorted([f for f in os.listdir(ref_dir) if f.endswith(".png")])
        small_frames = sorted([f for f in os.listdir(small_dir) if f.endswith(".png")])
    except Exception as e:
        return {"error": f"Failed to list frames: {e}"}
    
    # Use only overlapping frames (reference set intersection)
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
        
        result = compute_area_ratio(ref_path, small_path)
        if "error" in result:
            results.append({"frame": i, "error": result["error"]})
            continue
        
        # Mark frames with > 0.5 cm^2 error as unstable (relative to 56.25 cm² target)
        if result["absolute_error_cm2"] > 0.5:
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
        "mean_error_pct": float(100.0 * median_error / REF_AREA_CM2),
        "results": results,
    }


def main():
    """Run the shared-cylinder ratio measurement experiment."""
    
    print("=" * 80)
    print("Shared-Cylinder Ratio Measurement Experiment (Using OpenCV)")
    print("=" * 80)
    
    ref_dir = "/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface/data/reference_mask_propagated"
    small_dir = "/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface/data/small_rec_mask_propagated"
    
    if not os.path.exists(ref_dir) or not os.path.exists(small_dir):
        print(f"Error: Directories not found.")
        return
    
    ref_count = len([f for f in os.listdir(ref_dir) if f.endswith('.png')])
    small_count = len([f for f in os.listdir(small_dir) if f.endswith('.png')])
    
    print(f"\nAnalyzing frames from:")
    print(f"  Reference masks: {ref_count} files")
    print(f"  Small region masks: {small_count} files")
    
    # Run leave-one-view-out analysis
    print("\nRunning leave-one-view-out cross-validation...")
    loouv_result = leave_one_view_out_analysis(ref_dir, small_dir)
    
    # Save result to JSON
    output_path = "/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface/outputs/reports/shared_cylinder_ratio.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(loouv_result, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")
    
    # Report summary
    if "error" in loouv_result:
        print(f"\n⚠️  Error: {loouv_result['error']}")
        return
    
    print("\n=== SUMMARY ===")
    print(f"Total frames analyzed: {loouv_result['total_frames']}")
    print(f"Stable frames (good estimate): {loouv_result['stable_frames']}")
    if loouv_result.get("unstable_frame_indices"):
        print(f"Unstable frame indices: {loouv_result['unstable_frame_indices']}")
    
    mean_area = loouv_result.get('mean_area_cm2')
    mean_error_pct = loouv_result.get('mean_error_pct')
    
    print(f"\nMean area (cm²): {mean_area:.6f if mean_area else 'N/A'}")
    print(f"Target area: 56.25 cm²")
    if mean_area is not None:
        print(f"Absolute error: {abs(mean_area - 56.25):.6f} cm²")
        print(f"Relative error: {mean_error_pct:.4f}%")
    
    # Also report unstable frame counts
    if loouv_result.get("unstable_frame_indices"):
        print(f"\nUnstable frames (error > 0.5 cm²): {len(loouv_result['unstable_frame_indices'])} out of {loouv_result['total_frames']} frames")
        
    # Determine if this beats baseline
    current_best = 3.9814  # From small_rectangle_measurement.json
    target_area = 56.25
    
    if mean_area is not None and (mean_area / target_area < current_best / 56.25):
        print(f"\n✅ SUCCESS: New best result! Previous best was {current_best:.4f} cm²")
    else:
        print(f"\n⚠️  No improvement over baseline (baseline: {current_best:.4f} cm²)")


if __name__ == "__main__":
    main()
