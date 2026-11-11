#!/usr/bin/env python3
"""
Shared-Cylinder Ratio Measurement Experiment (using OpenCV, no PIL)
Corrected version: uses 4.0 cm² as target area for error calculation.
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
    """Use cv2 to read PNG and count foreground pixels."""
    try:
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
    
    # Reference represents 7.5x7.5 cm = 56.25 cm² (reference mask area)
    ref_fg_count = ref_parsed["fg_pixels"]
    total_ref = ref_parsed["total_pixels"]
    
    small_fg_count = small_parsed["fg_pixels"]
    total_small = small_parsed["total_pixels"]
    REF_AREA_CM2 = 56.25
    
    # Compute small area proportionally: (small_ratio / ref_ratio) * REF_AREA
    if ref_fg_count == 0 or total_ref == 0:
        return {"error": "Reference image has zero foreground or is empty"}
    
    small_area_cm2 = (small_fg_count / total_small) / (ref_fg_count / total_ref) * REF_AREA_CM2
    
    # Target small area is 4.0 cm², compute error relative to target
    absolute_error = abs(small_area_cm2 - 4.0)
    relative_error_pct = 100.0 * absolute_error / 4.0
    
    return {
        "fg_pixels_ref": ref_fg_count,
        "total_pixels_ref": total_ref,
        "fg_pixels_small": small_fg_count,
        "total_pixels_small": total_small,
        "area_cm2": float(small_area_cm2),
        "abs_error_cm2": float(absolute_error),
        "relative_error_pct": float(relative_error_pct),
    }


def leave_one_view_out_analysis(ref_dir: str, small_dir: str) -> dict:
    """Run leave-one-view-out cross-validation."""
    
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
    
    results = []
    unstable_frames = []
    
    for i, ref_fn in enumerate(overlapping_frames):
        small_fn = ref_fn
        ref_path = os.path.join(ref_dir, ref_fn)
        small_path = os.path.join(small_dir, small_fn)
        
        result = compute_area_ratio(ref_path, small_path)
        if "error" in result:
            results.append({"frame": i, "error": result["error"]})
            continue

        # Debug: print first 10 frames' area values
        if i < 10:
            print(f"Frame {i}: {ref_fn} -> area={result['area_cm2']:.4f}, error={result['abs_error_cm2']:.4f}")
        else:
            if i % 10 == 0:
                print(f"Frame {i}: {ref_fn} -> area={result['area_cm2']:.4f}, error={result['abs_error_cm2']:.4f}")
        
        # Mark frames with > 0.5 cm^2 error as unstable (relative to 4.0 cm² target)
        if result["abs_error_cm2"] > 0.5:
            unstable_frames.append(i)
        
        results.append({
            "frame": i,
            "area_cm2": result["area_cm2"],
            "abs_error_cm2": result["abs_error_cm2"],
        })
    
    print(f"\n=== Area Statistics ===")
    # Filter out error entries (failed parses)
    successful_results = [r for r in results if 'error' not in r]
    areas_computed = [r['abs_error_cm2'] for r in successful_results]
    unstable_count = len(unstable_frames)
    stable_count = len(successful_results)
    
    if areas_computed:
        min_area = min(areas_computed)
        max_area = max(areas_computed)
        print(f"Min area: {min_area:.4f}, Max area: {max_area:.4f}")
        print(f"Mean area: {sum(areas_computed)/len(areas_computed):.4f}")
    
    print(f"\nFrame counts:")
    print(f"  Total overlapping frames: {len(results)}")
    print(f"  Stable frames (error <= 0.5): {stable_count}")
    print(f"  Unstable frames (error > 0.5): {unstable_count}")
    
    if unstable_count > 0:
        unstable_frames_info = [results[f] for f in unstable_frames]
        print(f"\nUnstable frame details:")
        for uf in unstable_frames_info:
            print(f"  Frame {uf['frame']}: area={uf['area_cm2']:.4f}, error={uf['abs_error_cm2']:.4f}")
    
    # Filter out error entries (failed parses)
    successful_results = [r for r in results if 'error' not in r]

    print(f"\nAfter filtering:")
    print(f"  len(results) = {len(results)}")
    print(f"  len(successful_results) = {len(successful_results)}")
    
    if len(successful_results) == 0:
        return {
            "error": "All runs failed or were unstable",
            "median_area_cm2": None,
        }
    
    areas = [r["area_cm2"] for r in successful_results]
    abs_errors = [r["abs_error_cm2"] for r in successful_results]
    
    print(f"Computing median...")
    median_area = sum(areas) / len(areas)
    median_error = sum(abs_errors) / len(abs_errors)
    
    print(f"Median area: {median_area:.4f}, Median error: {median_error:.4f}")
    
    return {
        "total_frames": len(ref_frames),
        "stable_frames": len(successful_results),
        "unstable_frame_indices": unstable_frames,
        "mean_area_cm2": float(median_area),
        "mean_error_pct": float(100.0 * median_error / 4.0),
        "results": results,
    }


def main():
    print("=" * 80)
    print("Shared-Cylinder Ratio Measurement Experiment (Using OpenCV)")
    print("=" * 80)
    
    ref_dir = "/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface/data/reference_mask_propagated"
    small_dir = "/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface/data/small_rec_mask_propagated"
    
    ref_count = len([f for f in os.listdir(ref_dir) if f.endswith('.png')])
    small_count = len([f for f in os.listdir(small_dir) if f.endswith('.png')])
    
    print(f"\nAnalyzing frames from:")
    print(f"  Reference masks: {ref_count} files")
    print(f"  Small region masks: {small_count} files")
    
    loouv_result = leave_one_view_out_analysis(ref_dir, small_dir)
    
    output_path = "/home/geninfolab/Abishek_Chaudhari/BurnBuildSurface/outputs/reports/shared_cylinder_ratio.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(loouv_result, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")
    
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
    
    if mean_area is not None:
        print(f"\nMean area (cm²): {mean_area:.6f}")
        print(f"Target area: 4.0 cm²")
        print(f"Absolute error: {abs(mean_area - 4.0):.6f} cm²")
        print(f"Relative error: {mean_error_pct:.4f}%")
    else:
        print("\nMean area (cm²): N/A")
    
    if loouv_result.get("unstable_frame_indices"):
        print(f"\nUnstable frames (error > 0.5 cm²): {len(loouv_result['unstable_frame_indices'])} out of {loouv_result['total_frames']} frames")


if __name__ == "__main__":
    main()
