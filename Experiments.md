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

The current failure is therefore not simply “too few views.” It is a coupled
segmentation, calibration, and surface-model problem.

## Better accuracy strategy

The next implementation should use a **shared reference/small ratio**, not
independent absolute reconstructions:

1. Keep the 11 manual reference and small masks authoritative.
2. Use Canny/Hough/flow masks only as proposals for review, never as silent
   replacements.
3. Fit one cylinder to the union of the reference and small-region points
   using robust outlier rejection.
4. Project both regions onto that same cylinder and compute their areas in
   COLMAP units.
5. Report the ratio:

   `A_small_cm2 = (A_small_units / A_reference_units) * 56.25`

   The arbitrary COLMAP scale cancels completely.
6. Use per-view or leave-one-view-out estimates and report the median plus
   spread. A frame that changes the estimate substantially should be rejected
   with a diagnostic, not hidden by adding more propagated masks.
7. Use subpixel corner refinement (`cornerSubPix`) on the manually reviewed
   boundaries and fit the four sides jointly across anchor views.
8. Use a robust rectangle/cylinder intersection rather than percentile-clipping
   the point-cloud extents. Percentile clipping currently changes the measured
   patch dimensions when masks contain small boundary errors.

This approach directly targets the observed error: the numerator and
calibration denominator share camera, cylinder, and depth biases, so their
ratio is more stable than two separately fitted meshes.

## Further options if sub-percent accuracy is required

- Add manual corner annotations for every 10th–20th frame and interpolate a
  homography only between nearby reviewed anchors.
- Use a calibrated planar/cylindrical target with known corner coordinates to
  estimate camera scale and validate the reconstruction independently.
- Replace image-only optical flow with feature matching plus a homography
  constrained by four reviewed corners.
- Estimate a single global cylinder from all valid reference views, then hold
  its axis and radius fixed while measuring the small patch.
- Treat the four rectangle sides as observations with uncertainty and optimize
  corners, cylinder parameters, and projected edge alignment jointly.

No automatic method should be called an accuracy improvement until it beats
the 3.9814 cm² baseline on the known 4.0 cm² target.


#The experiment loop
The experiment runs on a dedicated branch

LOOP FOREVER: