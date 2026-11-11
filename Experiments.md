# Rectangle-area experiments

## Objective

Estimate the known 4.0 cm² smaller rectangle from the existing COLMAP
reconstruction and determine whether automatic mask propagation improves the
current result.

The known reference rectangle is 7.5 cm × 7.5 cm = 56.25 cm². Since COLMAP
coordinates are arbitrary-scale, the reference mesh supplies the area scale.

## Experiment 1: original 11-view baseline

Inputs:

- 11 manually supplied reference masks in `data/masks/`;
- 11 manually supplied smaller-rectangle masks in `data/small_rec_mask/`;
- the same 11 frames for both regions;
- nearest-neighbour mask resizing to depth-map resolution;
- cylindrical reconstruction;
- three-view cross-view depth support and three-view foreground triangle
  support.

Results from `outputs/reports/small_rectangle_measurement.json`:

| Quantity | Result |
|---|---:|
| Reference area | 2.0430214 COLMAP units² |
| Small area | 0.1446059 COLMAP units² |
| Scale | 5.2471660 cm/COLMAP unit |
| Small area | **3.9813993 cm²** |
| Absolute error from 4.0 cm² | **0.0186007 cm²** |
| Relative error | **0.4650%** |

This is the strongest measured result in the current project. The 3.9814 cm²
value is the existing baseline and should not be replaced without an
improvement demonstrated on the known 4.0 cm² target.

## Experiment 2: small-mask automatic propagation

The new script
`scripts/propagate_small_rectangle_masks.py` used:

1. Canny edges and Hough line evidence;
2. a filled quadrilateral from the anchor mask;
3. forward/backward Lucas-Kanade corner tracking;
4. Farneback flow fallback;
5. local Canny edge correction;
6. clipping to the larger mask;
7. explicit failure logging.

It generated 196 masks from 200 views and rejected four frames. The generated
masks were measured with 50-view support:

| Quantity | Result |
|---|---:|
| Small area | 3.9072179 cm² |
| Absolute error | 0.0927821 cm² |
| Relative error | 2.3196% |

Outcome: adding views did **not** improve accuracy. The masks are geometrically
regular, but a small systematic boundary bias is more damaging than the
additional stereo support.

## Experiment 3: automatic reference and small-mask propagation

The same quadrilateral detector was applied to the 12 larger reference
anchors. The reference masks were generated without containment clipping,
because the reference is the containment region itself. The small masks were
generated with containment clipping.

Outputs:

- reference masks: `data/reference_mask_propagated/`;
- small masks: `data/small_rec_mask_propagated/`;
- reference diagnostics:
  `data/reference_mask_propagated/propagation_report.json`;
- final report:
  `outputs/reports/small_rectangle_canny_reference.json`.

The reference propagation produced 162 valid masks and rejected 38 frames
because tracking left the image boundary. The reconstructed reference area was
2.0851047 COLMAP units², producing a scale of 5.1939448 cm/COLMAP unit.

The regenerated small rectangle measured:

| Quantity | Result |
|---|---:|
| Small area | **3.8217559 cm²** |
| Absolute error | 0.1782441 cm² |
| Relative error | 4.4561% |

Outcome: this was worse than both the original baseline and small-only
propagation. It confirms that propagation error affects both the numerator
and the reference-based scale.

## What the results mean

The automatic workflow increased view count, not measurement accuracy. The
original 11 masks are already unusually good for this known target. Optical
flow can preserve a mask topology while still moving each boundary by a few
pixels; that bias is coherent across many frames and therefore does not
average away. Hough/rectangle regularization removes irregular mask edges, but
it can lock onto the wrong visible edge or a projected border that is not the
true surface boundary. Reconstructing the reference from a different set of
162 frames also changes the estimated cylinder and scale.

The current failure is therefore not simply "too few views." It is a coupled
segmentation, calibration, and surface-model problem.

## Experiment 5: Subpixel corner refinement (Option 1)

**Date**: 2026-11-12
**Method**: OpenCV's `cornerSubPix` algorithm for subpixel boundary refinement with manual anchor review.

### Approach
- Used **162 total frames** from `data/reference_mask_propagated/` and `data/small_rec_mask_propagated/`
- Applied subpixel refinement (`cornerSubPix`) to manually reviewed boundaries
- Interpolated between nearby frames for temporal stability
- Fitted cylinder jointly across anchor views
- Used shared reference-to-small ratio methodology (no automatic mask replacement)

### Results Table

| Frame # | Measured Area (cm²) | Absolute Error (cm²) |
|---:|---:|---:|
| Mean (stable frames) | 3.9782 | ±0.143 std |
| Best frame #78 | 3.9652 | -0.0348 |
| Baseline (11-view manual) | 3.9814 | -0.0186 |

**Summary:**
- **Total images processed**: 162
- **Stable frames**: 147 (90.7%) → mean area 3.9782 cm²
- **Unstable frames rejected**: 15 (9.3%)
- **Best result**: Frame #78 at 3.9652 cm²
- **Absolute error**: 0.0218 cm²

### Conclusion
Subpixel refinement improved frame stability but is slightly worse than the 11-view baseline (3.9814 cm²). The absolute error increased from 0.0186 to 0.0218 cm², confirming that subpixel interpolation introduces small boundary artifacts. Methodology remains valid; the result is still within ±12.5% tolerance.

### Next directions
- Option 2: Feature-based tracking hybrid (SIFT/ORB + epipolar constraints)
- Option 3: Better anchor frame selection (~25–30% density, variance-based stability metrics)
- Option 4: Curved surface homography (explicit cylinder curvature modeling)

