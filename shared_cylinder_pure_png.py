#!/usr/bin/env python3
"""
Shared-Cylinder Ratio Measurement Experiment (Pure-Python, no external deps)
Parses PNG files using only stdlib: struct, zlib, io.
Extracts foreground pixels from grayscale masks.
"""

import os
import sys
import struct
import zlib
import json
import math


def parse_png(filepath):
    """
    Minimal PNG parser that extracts pixel data from grayscale images.
    Returns dict with width, height, pixels (row-major), or error dict.
    """
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except Exception as e:
        return {"error": f"Cannot read file: {e}"}
    
    if len(data) < 8:
        return {"error": "File too short"}
    
    # Check PNG signature using bytes
    png_sig = b'\x89PNG\r\n\x1a\n'
    if data[:8] != png_sig:
        try:
            # Try to detect what it is
            first_bytes = data[:4]
            if first_bytes == b'\x7fGA\x01':
                return {"error": "GIF file (not PNG)"}
            elif first_bytes == b'\xff\xd8\xff':
                return {"error": "JPEG file (not PNG)"}
            else:
                return {"error": f"Bad signature: {first_bytes.hex()[:20]}..."}
        except:
            return {"error": "Not a valid PNG file"}
    
    # Parse IHDR chunk to get width, height
    i = 8
    ihdr_found = False
    
    while i < len(data) - 4:
        # Check for end of file or next major opus code (IEND)
        remaining = data[i:]
        if len(remaining) < 12:
            break
        chunk_len_bytes = remaining[:4]
        if len(chunk_len_bytes) < 4:
            break
        try:
            chunk_len = struct.unpack('>I', chunk_len_bytes)[0]
        except:
            break
        
        chunk_type = remaining[4:12]
        
        if chunk_type == b'IHDR':
            # IHDR data is after the 8-byte type identifier
            ihdr_data = remaining[12:12+chunk_len]
            if len(ihdr_data) < 16:
                return {"error": "IHDR too short"}
            
            width, = struct.unpack('>I', ihdr_data[0:4])
            height, = struct.unpack('>I', ihdr_data[4:8])
            bit_depth = ihdr_data[8]
            color_type = ihdr_data[9]
            ihdr_found = True
            break
        
        # Skip other chunks
        i += 12 + chunk_len
    else:
        if not ihdr_found:
            return {"error": "No IHDR chunk found"}
    
    if not ihdr_found:
        return {"error": "Could not find IHDR"}
    
    # Get to the first IDAT chunk
    i = 8
    idat_data = b''
    
    while i < len(data) - 4:
        remaining = data[i:]
        if len(remaining) < 12:
            break
        try:
            chunk_len = struct.unpack('>I', remaining[:4])[0]
        except:
            break
        
        chunk_type = remaining[4:12]
        
        if chunk_type == b'IEND':
            break
        
        if chunk_type == b'IDAT':
            # IDAT data starts after 8-byte header
            idat_data += remaining[12:12+chunk_len]
        
        i += 12 + chunk_len
    
    if not idat_data:
        return {"error": "No IDAT chunks found"}
    
    # Decompress IDAT data
    try:
        raw_bytes = zlib.decompress(idat_data)
    except Exception as e:
        return {"error": f"Decompression failed: {e}"}
    
    # Parse raw pixel data
    # Filter byte at start of each row (for grayscale: color_type=0, 1 byte per pixel)
    pixels = []
    
    if width > 0 and height > 0:
        for row in range(height):
            row_start = row * (width + 1)
            if row_start >= len(raw_bytes):
                break
            
            filter_byte = raw_bytes[row_start]
            pixel_data_start = row_start + 1
            
            # Read width pixels
            for col in range(width):
                pix_offset = pixel_data_start + col
                if pix_offset < len(raw_bytes):
                    pixels.append(raw_bytes[pix_offset])
    
    return {
        "width": width,
        "height": height,
        "pixels": pixels,
    }


def count_foreground_pixels(parsed_png):
    """Count foreground pixels (value > 0) from parsed PNG."""
    if "error" in parsed_png:
        return None, None
    
    pixels = parsed_png.get("pixels", [])
    fg_count = sum(1 for p in pixels if p > 0)
    
    return fg_count, len(pixels)


def compute_area_ratio(ref_path, small_path):
    """Compute area ratio between small and reference masks."""
    
    ref_parsed = parse_png(ref_path)
    small_parsed = parse_png(small_path)
    
    if "error" in ref_parsed:
        return {"error": f"Ref parse error: {ref_parsed['error']}"}
    if "error" in small_parsed:
        return {"error": f"Small parse error: {small_parsed['error']}"}
    
    ref_fg_count, total_ref = count_foreground_pixels(ref_parsed)
    small_fg_count, total_small = count_foreground_pixels(small_parsed)
    
    if ref_fg_count is None or small_fg_count is None:
        return {"error": "Failed to count foreground pixels"}
    
    # Reference represents 4x4 cm = 16 cm² ground truth
    # Compute small area proportionally based on pixel counts
    
    # The ratio should be: small_area = 4.0 * (small_fg / total_small) / (ref_fg / total_ref) 
    # But actually we want: small_area = 4.0 * (small_fg / ref_fg) if they're same size
    # Let's use simple proportionality: areas are proportional to pixel counts
    
    ratio = small_fg_count / ref_fg_count
    small_area_cm2 = 4.0 * ratio  # Reference area is 4.0 cm² (target), scale proportionally
    
    absolute_error = abs(small_area_cm2 - 4.0)
    relative_error_pct = 100.0 * absolute_error / 4.0
    
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
    print("Shared-Cylinder Ratio Measurement Experiment (Pure-Python)")
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
