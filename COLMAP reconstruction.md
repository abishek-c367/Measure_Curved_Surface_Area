# COLMAP reconstruction

## Why `reconstruct` takes a long time

The command:

```bash
python main.py reconstruct
```

does much more than create a mesh. With 200 registered images, it processes
high-resolution images, depth maps, masks, and cross-view geometry. The most
expensive operation is usually COLMAP PatchMatch Stereo, followed by the
cross-view filtering of masked 3D points.

The current images are approximately 1906 x 1071 after undistortion. The
amount of work increases with:

- Number of images: 200 views require 200 depth-map computations.
- Image resolution: every pixel can be considered for depth and back-projection.
- Mask size: larger white regions produce more candidate 3D points.
- GPU availability and CUDA compatibility.
- `max_points_per_image`: `0` currently means no sampling limit.
- `min_views`: higher values require more cross-view checks.

## Steps performed by `python main.py reconstruct`

### 1. Create/check output directories

The pipeline ensures the configured data and output directories exist.

### 2. Validate masks

It checks that every undistorted image has a corresponding mask in
`data/masks/`, and that each mask:

- Exists.
- Has the same dimensions as its image.
- Is not empty.

Current mask validation is performed before any depth processing.

### 3. Run COLMAP PatchMatch Stereo

The pipeline runs COLMAP:

```text
patch_match_stereo
```

using the undistorted workspace:

```text
data/colmap_output/dense/
```

PatchMatch estimates a depth value for pixels in every registered view by
matching image features across neighboring views. It evaluates many candidate
depths and repeatedly refines them. This is normally the dominant runtime
stage and is GPU-oriented.

Current settings are in `config.yaml`:

```yaml
geom_consistency: true
window_radius: 5
window_step: 1
num_samples: 15
num_iterations: 5
```

Depth maps are written under:

```text
data/colmap_output/dense/stereo/depth_maps/
```

### 4. Load cameras, poses, depth maps, and masks

For each registered image, the pipeline loads:

- Camera intrinsics from the undistorted COLMAP model.
- Camera pose from `images.txt`.
- The PatchMatch depth map.
- The propagated sticky-note mask.

Only views with all required data are used.

### 5. Back-project masked pixels into 3D

For each view, every white mask pixel with a valid positive depth is converted
from image coordinates into a 3D point using the camera intrinsics and pose.

Because `max_points_per_image: 0`, all valid masked pixels are currently used.
For a large sticky-note mask, this can create millions of candidate points.

### 6. Cross-view geometric filtering

Each candidate point is projected into every other registered view. A point
receives support when:

- Its projection is in front of the camera.
- Its projected pixel lies inside the other image.
- That pixel is white in the other mask.
- The other view has a valid depth value.
- The projected depth agrees with the measured depth within
  `depth_relative_tolerance: 0.03`.

The current `min_views: 2` setting keeps points supported by at least two
views. With 200 views, this repeated projection and depth comparison can be
computationally expensive.

### 7. Build and clean the point cloud

Surviving points from all source views are combined into one point cloud and
saved as:

```text
outputs/pointcloud/burn_points.ply
```

The pipeline can voxel-downsample the cloud if `voxel_size` is greater than
zero. It also removes statistical outliers using:

```yaml
statistical_outlier_neighbors: 20
statistical_outlier_std_ratio: 2.0
```

### 8. Create the surface mesh

The point cloud is used to estimate normals, orient those normals, and create
an open surface using Ball Pivoting. The configured radii are based on the
median nearest-neighbor spacing:

```yaml
bpa_radii_multipliers: [1.5, 2.5, 4.0]
```

Small disconnected mesh components are removed. Outputs are:

```text
outputs/mesh/burn_surface.ply
outputs/mesh/burn_surface.obj
```

### 9. Calculate and save the measurement report

The mesh area and run settings are saved to:

```text
outputs/reports/measurement.json
```

COLMAP has arbitrary monocular scale. Since
`cm_per_colmap_unit` is currently `null`, the report cannot claim physical
square-centimeter units until a scale reference is supplied.

## Why the current run is especially expensive

The current configuration uses 200 views, full-resolution depth estimation,
all valid masked pixels, and all-view cross-checking. In particular:

```yaml
max_points_per_image: 0
```

means there is no candidate-point cap. The sticky-note mask covers a
substantial image region, so millions of pixels may be back-projected and
tested against the other views.

## Outputs and progress

The main stages write these files:

| Stage | Output |
|---|---|
| PatchMatch | `data/colmap_output/dense/stereo/depth_maps/` |
| Point cloud | `outputs/pointcloud/burn_points.ply` |
| Mesh | `outputs/mesh/burn_surface.ply` and `.obj` |
| Measurement | `outputs/reports/measurement.json` |

If only depth maps exist, PatchMatch completed but point-cloud processing is
still running or failed afterward. If the point cloud exists, the expensive
back-projection/filtering stage completed. The mesh and JSON report indicate
the full reconstruction completed.

## Practical ways to reduce runtime

1. Keep only the best overlapping views instead of all 200 images.
2. Set `max_points_per_image` to a bounded value, such as `100000`, to reduce
   cross-view processing.
3. Use a positive `voxel_size` to reduce point-cloud size before meshing.
4. Reduce PatchMatch iterations or samples only if quality remains acceptable.
5. Confirm that the CUDA-enabled COLMAP executable is being used.

These are quality/runtime trade-offs. Do not reduce settings blindly; inspect
the resulting point cloud and mesh after each change.
