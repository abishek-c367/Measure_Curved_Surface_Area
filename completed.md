# Completed work

## Scope

The pipeline was completed through dense reconstruction, foreground-constrained
meshing, OBJ export, and reprojection validation.

## What was already done

1. The supplied video was sampled into 200 JPEG input images, one randomly
   selected frame from each of 200 equal time intervals.
2. The 200 source images were saved in `data/images/`.
3. COLMAP feature extraction was run on those images.
4. COLMAP exhaustive feature matching was run.
5. COLMAP sparse mapping was run.
6. The sparse model was converted to text format.
7. COLMAP image undistortion was run.
8. The undistorted sparse model was converted to text format.

The sparse mapper registered all 200 sampled frames. All 200 therefore appear
in the undistorted image set.

## Commands used

From the project directory:

```bash
python scripts/extract_video_frames.py --seed 42
python main.py prepare
```

The COLMAP compatibility path uses `--FeatureMatching.use_gpu` for the
installed COLMAP 4.2.1 build.

## Delivered files

- Source video: `data/videos/3D reconstruction .mp4`
- 200 sampled source images: `data/images/frame_0001.jpg` through
  `data/images/frame_0200.jpg`
- COLMAP database: `data/colmap_output/database.db`
- Sparse reconstruction: `data/sparse/0/`
- Sparse text model: `data/sparse/0/txt/`
- Registered undistorted images: `data/colmap_output/dense/images/`
- Undistorted COLMAP model: `data/colmap_output/dense/sparse/`
- Undistorted text model: `data/colmap_output/dense/sparse/txt/`
- Dense-stage configuration files: `data/colmap_output/dense/stereo/`

## Mask validation

The propagated masks are available in:

```text
data/masks/
```

The generated masks have the same filename stem as the undistorted image:

```text
data/colmap_output/dense/images/frame_0001.jpg
data/masks/frame_0001.png
```

Validation completed successfully:

```bash
python scripts/check_inputs.py
```

Result: 200 images, 0 missing masks, 0 empty masks, and 0 dimension
mismatches. Review the propagated masks before reconstruction because optical
flow propagation is an approximation and may require manual correction.

## Mask propagation

Twelve manually created reference masks were supplied in `data/masks/` at
frames 1, 20, 30, 40, 60, 80, 100, 120, 140, 160, 180, and 200. The
reference files use the `frame_NNNN_mask.jpg` naming pattern.

The reusable propagation script is:

```bash
python scripts/propagate_masks.py
```

It uses dense Farneback optical flow between consecutive undistorted images,
propagates each target from its nearest reference mask, detects and corrects
white-background/black-object reference polarity, keeps the largest connected
foreground component, and saves canonical outputs as
`data/masks/frame_NNNN.png`. The original reference JPEG masks are retained.

## Foreground-only reconstruction

The following changes were implemented and verified successfully:

1. White mask pixels are used as foreground. Black mask pixels are excluded
   during backprojection.
2. Mesh triangles are checked against the masks by projecting their vertices,
   edge midpoints, and centroids into the registered views.
3. Triangles are retained only when all sampled points are inside the white
   foreground mask in the configured minimum number of views.
4. The meshing stage retries smaller Ball Pivoting radii when a candidate mesh
   is rejected.
5. Triangle selection was corrected to select triangle indices rather than
   mistakenly treating them as vertex indices.
6. Reconstruction stops with an explicit error if no foreground-constrained
   mesh can be produced.

The final configuration requires support from 20 views:

```yaml
meshing:
  foreground_min_views: 20
```

This removed the earlier behavior where a triangle could survive after being
inside the mask in only one view.

## Verification

The final OBJ was reprojected into the 200 registered views. A sample of
100,000 mesh triangles was checked:

- Minimum foreground-mask support: 20 views
- Median foreground-mask support: 66 views
- Maximum foreground-mask support: 186 views
- Sampled triangles below the 20-view threshold: 0

## Final outputs

- Foreground-constrained OBJ:
  `outputs/mesh/burn_surface.obj`
- Foreground-constrained PLY:
  `outputs/mesh/burn_surface.ply`
- Reconstruction report:
  `outputs/reports/measurement.json`

The report records the selected meshing settings, including
`foreground_min_views: 20`.

## Smaller rectangle area experiment

The smaller-rectangle masks were supplied in:

```text
data/small_rec_mask/
```

They were available for 11 frames:

```text
frame_0001, frame_0020, frame_0040, frame_0060, frame_0080,
frame_0100, frame_0120, frame_0140, frame_0160, frame_0180, frame_0200
```

The reference masks in `data/masks/` and the smaller-rectangle masks were
processed using the same 11 frames. The masks were resized with nearest
neighbour interpolation to the COLMAP depth-map resolution. A focused
cylindrical reconstruction was then run for each region using:

- minimum cross-view depth support: 3 views;
- depth relative tolerance: 0.02;
- voxel size: 0.001 COLMAP units;
- minimum foreground triangle support: 3 views.

The resulting meshes are:

- `outputs/mesh/reference_rectangle.obj`
- `outputs/mesh/reference_rectangle.ply`
- `outputs/mesh/small_rectangle.obj`
- `outputs/mesh/small_rectangle.ply`

### Calibration mathematics

The known reference rectangle has:

```text
W_ref = 7.5 cm
H_ref = 7.5 cm
A_ref,cm2 = W_ref × H_ref = 56.25 cm²
```

The reconstructed reference mesh area was:

```text
A_ref,u = 2.0430214084 COLMAP units²
```

Because COLMAP has arbitrary scale, the centimetres-per-COLMAP-unit scale was
computed from area:

```text
s = sqrt(A_ref,cm2 / A_ref,u)
  = sqrt(56.25 / 2.0430214084)
  = 5.2471660098 cm/COLMAP unit
```

The smaller rectangle reconstructed area was:

```text
A_small,u = 0.1446059377 COLMAP units²
```

Area scales by the square of the linear scale:

```text
A_small,cm2 = A_small,u × s²
             = 0.1446059377 × (5.2471660098)²
             = 3.9813992940 cm²
```

### Current estimate

Under the assumption that the masks in `data/masks/` isolate only the known
7.5 cm × 7.5 cm reference rectangle, the estimated smaller-rectangle surface
area is:

```text
3.9814 cm²
```

The estimate is not yet a validated accuracy claim. Only 11 views had
smaller-rectangle masks, so the focused experiment used three-view support
instead of the production 20-view foreground threshold. The reference
cylinder fit had a 95th-percentile residual of `0.0351036` COLMAP units and
the smaller-rectangle fit had a 95th-percentile residual of `0.0119041`
COLMAP units. Add masks for more views and validate against a physical
cylindrical object with a known patch area before using the result for research
or clinical conclusions.

## Automatic small-rectangle propagation experiment

The reusable pipeline is:

```bash
python scripts/propagate_small_rectangle_masks.py
python scripts/measure_small_rectangle.py
```

The propagation script detects each anchor quadrilateral with Canny/Hough
evidence, tracks corners with forward/backward Lucas-Kanade optical flow,
falls back to dense Farneback flow when sparse tracking fails, performs local
Canny edge correction, clips every generated mask to the corresponding
larger mask, and writes rejected frames to
`data/small_rec_mask_propagated/propagation_report.json`. It generated 196 of
200 masks; frames 91, 191, 192, and 130 were rejected rather than silently
extrapolated.

Using the existing COLMAP depth maps and the same reference calibration, the
like-for-like measurement report is:

| Workflow | Views | Area (cm²) | Absolute error |
|---|---:|---:|---:|
| Current 11-view baseline | 11 | 4.0087 | 0.0087 |
| Propagated masks, 50-view support | 196 | 3.9072 | 0.0928 |

Therefore the measured accuracy gain is **-0.0841 cm²** (the propagated
workflow is 0.0841 cm² farther from the 4.0 cm² truth, or 2.32% relative
error versus 0.22% for the baseline). On this dataset, propagation increases
coverage but does not improve the already near-exact baseline; rejected frames
and propagated masks should be reviewed before using the expanded view set.

## Canny/Hough reference-mask recalibration

The same filled-quadrilateral detector is now applied to the larger reference
anchors (`data/masks/frame_*_mask.jpg`) with no optical-flow mask warping. The
generated reference masks are in `data/reference_mask_propagated/`; the small
rectangle masks were regenerated in `data/small_rec_mask_propagated/`.

Run:

```bash
python scripts/propagate_small_rectangle_masks.py \
  --anchors data/masks --anchor-pattern '*_mask.jpg' --no-containment \
  --output data/reference_mask_propagated
python scripts/propagate_small_rectangle_masks.py \
  --anchors data/small_rec_mask --anchor-pattern '*_small_rec.jpg' \
  --larger-masks data/masks --output data/small_rec_mask_propagated
python scripts/measure_small_rectangle.py \
  --reference data/reference_mask_propagated \
  --propagated data/small_rec_mask_propagated
```

The reference propagation produced 162 valid masks from 200 views; 38 frames
were rejected because tracked corners left the image boundary. Using the
known `56.25 cm²` reference area, the recalculated scale is
`5.1939447882 cm/COLMAP unit`, based on `2.0851047099 COLMAP units²`.
The regenerated small rectangle measures **3.8218 cm²**, with absolute error
`0.1782 cm²` or `4.46%` against the known 4 cm² area. The complete result is
in `outputs/reports/small_rectangle_canny_reference.json`.
