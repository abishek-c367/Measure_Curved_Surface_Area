# BurnBuildSurface

A modular Python photogrammetry pipeline for producing an **isolated 3D surface patch** from manually segmented burn regions. Burn segmentation is intentionally outside this project: you provide one binary mask per undistorted image.

> Research prototype only. Not clinically validated. Do not use as the sole basis for clinical decisions.

## What it does

1. Uses the complete photographs for COLMAP feature extraction, matching and sparse camera reconstruction.
2. Undistorts images with COLMAP.
3. Pauses for you to manually create burn masks.
4. Runs COLMAP PatchMatch Stereo to produce depth maps.
5. Back-projects only pixels inside the burn masks into 3D.
6. Filters candidate points using other views' burn masks and depth maps.
7. Fuses and cleans the burn-only point cloud.
8. Reconstructs either an open Ball-Pivoting patch or an experimental
   cylinder-constrained patch.
9. Calculates mesh surface area and exports PLY, OBJ and JSON.

Normal skin is retained in the input photographs because it helps camera localization, but it is excluded from the final candidate point cloud by the masks.

## Requirements

- Python 3.10+ (3.11 recommended)
- CUDA-enabled COLMAP installed at `.tools/colmap-cuda`, or set `colmap_executable` in `config.yaml`
- Windows, Linux or macOS
- Dense stereo is computationally expensive. **COLMAP PatchMatch Stereo is GPU-oriented and generally requires a CUDA-capable NVIDIA GPU/build.** On a laptop with integrated graphics and no NVIDIA GPU, sparse camera reconstruction may work, but this dense stage may not run. In that case, run the dense stage on a CUDA workstation/server or replace the depth backend with a CPU-capable multi-view stereo implementation; this project currently wires COLMAP PatchMatch Stereo.

Install:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The default configuration uses `scripts/colmap`, which launches the downloaded
CUDA-enabled build and its local CUDA 12 runtime libraries. To install it on
Ubuntu 24.04:

```bash
mkdir -p .tools
curl -fL -o .tools/COLMAP.zip \
  https://github.com/lyehe/build_gpu_colmap/releases/download/v4.2.1/COLMAP-4.2.1-ubuntu-24.04-CUDA-Caspar.zip
unzip .tools/COLMAP.zip -d .tools/colmap-cuda
mkdir -p .tools/cuda12-pkgs .tools/cuda12
(cd .tools/cuda12-pkgs && apt-get download cuda-cudart-12-8 libcublas-12-8 libcusolver-12-8 libnvjitlink-12-8)
for package in .tools/cuda12-pkgs/*.deb; do dpkg-deb -x "$package" .tools/cuda12; done
```

Check: `./scripts/colmap -h`

## Project layout

```text
BurnBuildSurface/
├── main.py
├── config.yaml
├── requirements.txt
├── README.md
├── data/
│   ├── images/              # original photographs
│   └── masks/               # manually created masks
├── data/colmap_output/      # COLMAP database and undistorted/dense workspace
├── data/sparse/              # sparse camera reconstruction
├── outputs/
│   ├── pointcloud/
│   ├── mesh/
│   └── reports/
├── burnbuild/
│   ├── config.py
│   ├── colmap_runner.py
│   ├── colmap_io.py
│   ├── depth_io.py
│   ├── masks.py
│   ├── backproject.py
│   ├── multiview.py
│   ├── pointcloud.py
│   ├── meshing.py
│   ├── measurement.py
│   └── pipeline.py
└── scripts/check_inputs.py
```

## Usage

### 1. Extract images from the supplied video

From the project directory, run:

```bash
python scripts/extract_video_frames.py
```

The stage-1 script selects one random frame from each of 200 equal time
intervals in `data/videos/3D reconstruction .mp4` and saves the 200 JPEG
images in `data/images/`. Use `--seed` when reproducible selections are
needed, or `--video` and `--output` to override the default paths.

### 2. Add images

Put JPG/JPEG/PNG/TIF/TIFF images of the same stationary body part in `data/images/`. Images must overlap substantially and show the same pose. Avoid motion, blur, changing zoom/focus, changing lighting, and strong reflections. Capture the burn boundary from multiple views.

### 2. Configure

Edit `config.yaml`:

- `colmap_executable`: `colmap` if on PATH, otherwise full executable path.
- `camera_model`: commonly `OPENCV` or `SIMPLE_RADIAL`; use `PINHOLE`/`SIMPLE_PINHOLE` for already undistorted imagery.
- `single_camera`: true only if the same camera and unchanged zoom/focus are used for all images.
- `max_image_size`: `-1` means do not resize during undistortion.
- `use_gpu`: set according to your COLMAP build.
- `min_views`: number of views required to support a 3D point; 5 is a strict starting point for noisy depth.
- `depth_relative_tolerance`: relative projected-vs-measured depth tolerance; 0.005 is a strict starting point for thin surfaces.
- `max_points_per_image`: 0 means all valid mask pixels; a positive number caps samples for memory/runtime.
- `voxel_size`: 0 automatically skips voxel downsampling; otherwise COLMAP-world units.
- `cm_per_colmap_unit`: set only after establishing metric scale from a known reference length. Otherwise leave null.
- `surface_model`: `cylindrical` uses the selected experiment described below;
  `bpa` preserves the unconstrained baseline.
- `foreground_min_views`: minimum number of views in which a generated
  triangle must project entirely inside the white mask.
- `cylinder_axial_resolution` and `cylinder_angular_resolution`: grid
  resolution for the cylindrical experiment.

### 3. Prepare camera reconstruction

From the project root:

```bash
python main.py prepare
```

This runs COLMAP feature extraction, exhaustive matching, sparse mapping, model conversion, and image undistortion.

Inspect:
- `data/sparse/`
- `data/colmap_output/dense/images/`

COLMAP may fail to register images if the scene is textureless, blurry, reflective, or moving. Resolve registration issues before proceeding.

### 4. Manually segment undistorted images

Create a binary mask for each image in `data/colmap_output/dense/images/`.

Save the mask in `data/masks/` using the same filename stem. Example:

- image: `IMG_001.jpg`
- mask: `IMG_001.png`

Mask dimensions must exactly match the corresponding undistorted image. White/nonzero = burn; black/zero = everything else. Use grayscale or binary PNG. Do not annotate the original distorted image unless you separately transform the mask to the undistorted coordinate system.

Validate:

```bash
python scripts/check_inputs.py
```

### 5. Run dense reconstruction and mesh generation

```bash
python main.py reconstruct
```

This runs PatchMatch Stereo, loads COLMAP depth maps, extracts masked 3D
points, performs cross-view mask/depth consistency filtering, reconstructs the
configured surface model, and writes the measurement report.

### 6. View outputs

```bash
python main.py visualize
```

Outputs:

| Path | Meaning |
|---|---|
| `outputs/pointcloud/burn_points.ply` | filtered burn-only point cloud |
| `outputs/mesh/burn_surface.ply` | open burn surface mesh |
| `outputs/mesh/burn_surface.obj` | OBJ version |
| `outputs/reports/measurement.json` | area, units, counts and settings |

Open PLY/OBJ files in CloudCompare, MeshLab or Blender.

## Research plan for a curved cylindrical patch

The project objective is to estimate the area of a segmented patch lying on a
cylindrical body. A flat image measures projected area, not true surface area.
The reconstruction therefore needs both correct camera geometry and a surface
model that can represent curvature.

### Candidate solution directions

1. **Free-form photogrammetry (current BPA baseline).** COLMAP estimates
   per-pixel depth and Ball Pivoting creates a mesh. This is general, but
   photometric stereo is weak on skin or other texture-poor surfaces. Large
   holes can also be bridged by the meshing step.
2. **Cylinder-constrained reconstruction (chosen experiment).** Fit a
   cylinder to the reliable foreground 3D points, create a regular grid on
   that cylinder, and keep only grid triangles supported by the white masks in
   many views. This uses the known shape of the body to fill missing interior
   depth without inventing a flat patch.
3. **Image-to-cylinder unwrapping with dense correspondence.** Estimate the
   cylindrical geometry first, unwrap each view to cylinder coordinates, and
   match pixels in the unwrapped domain. This can provide dense coverage but
   requires more careful calibration and correspondence handling.
4. **Learned multi-view stereo.** MVSNet-style models can be tested when
   training-domain and GPU requirements are acceptable. They still need a
   geometric prior and mask validation for a weakly textured cylindrical
   surface.
5. **Edge/tangency cylinder fitting.** Detect the two apparent cylinder
   boundaries and solve the cylinder from multi-view tangency constraints.
   This is promising for very weak texture, but requires clean visible edges
   and is less directly compatible with the current dense-depth pipeline.

The literature supports this choice. A continuous cylindrical reconstruction
method uses calibrated stereo geometry and cylinder-specific image
transformations to recover surface points
[PMC6308718](https://pmc.ncbi.nlm.nih.gov/articles/PMC6308718/). Recent work on
weakly textured cylindrical objects uses multi-view tangent constraints and
reports that a cylinder prior can outperform ordinary MVS when texture is
insufficient
[Zhao et al. 2025](https://dpcv.whu.edu.cn/info/1030/2145.htm). COLMAP's
PatchMatch approach remains a useful baseline, but its photometric assumptions
are a known weakness on textureless or non-Lambertian surfaces
[COLMAP bibliography](https://colmap.github.io/bibliography.html).

### Chosen experiment: cylinder-constrained mesh

The default experiment is now:

```yaml
meshing:
  surface_model: cylindrical
  foreground_min_views: 20
```

The implementation:

1. Uses the existing masked and cross-view-filtered 3D points.
2. Estimates a cylinder axis, circular cross-section, radius, and fit
   residual.
3. Creates a regular grid in axial position and angle on that cylinder.
4. Projects the grid triangles into every registered image.
5. Keeps a triangle only when all of its sampled points are white-mask pixels
   in at least 20 views.
6. Computes the area from the resulting curved triangular surface.

The baseline can be selected with:

```yaml
meshing:
  surface_model: bpa
```

The cylindrical model is an experiment, not yet a validated clinical
measurement method. The fit residual must be inspected. A large residual means
that the object is not well described by one cylinder, the point cloud still
contains outliers, or the camera/depth reconstruction is inaccurate.

### Metric scale and area evaluation

COLMAP has arbitrary global scale. The recommended calibration experiment is
to include a rigid reference with a known length or a known 7.5 cm by 7.5 cm
region. Estimate centimetres per COLMAP unit from a side length, then set
`measurement.cm_per_colmap_unit`. Area scales by the square of this factor:

```text
area_cm2 = area_colmap_units2 * scale_cm_per_unit^2
```

Do not compare area values in cm² until this scale is independently measured.
For validation, use cylindrical test objects with known radius and marked
patch boundaries. Compare:

- reference area versus reconstructed area;
- relative area error;
- cylinder-fit residual;
- mask reprojection support;
- repeatability across camera paths and lighting.

Run the same dataset through both `surface_model: bpa` and
`surface_model: cylindrical`. The chosen method should be the one with lower
area error on known test objects, not simply the one with the visually denser
mesh.

## Mathematical method

For an undistorted burn pixel `(u,v)` with COLMAP depth `d` and intrinsic matrix `K`:

\[
P_c=dK^{-1}[u,v,1]^T
\]

COLMAP image poses are world-to-camera:

\[
P_c=RP_w+t
\]

Thus:

\[
P_w=R^T(P_c-t)
\]

For each candidate 3D point, the pipeline projects it into other registered views. It counts support when the projected pixel is inside that view's burn mask and its measured depth agrees with the point's camera-space depth within the configured relative tolerance. Points supported by fewer than `min_views` are removed.

Ball Pivoting connects the filtered points into an open triangular patch. The surface area is:

\[
A=\sum_{f=1}^{N_f}\frac12\|(B_f-A_f)\times(C_f-A_f)\|
\]

COLMAP monocular SfM has arbitrary global scale. If `s` is centimetres per COLMAP unit, then `A_cm2 = s² A`. Without a valid scale calibration, the report explicitly labels area as arbitrary COLMAP units squared. Do not report cm² without scale calibration.

## Important implementation notes and limitations

- The masks must be drawn on the **undistorted** images, because depth maps and camera intrinsics refer to that coordinate system.
- The code supports undistorted `PINHOLE` and `SIMPLE_PINHOLE` camera models for back-projection. COLMAP's image undistorter normally writes an undistorted pinhole model. If your dense model uses another model, the pipeline stops rather than silently applying incorrect intrinsics.
- Depth maps may be lower resolution than undistorted images. Masks are resized with nearest-neighbour interpolation and intrinsics are scaled to the depth-map resolution.
- This initial implementation uses photometric depth maps and a practical cross-view test. It is not a replacement for COLMAP's full probabilistic stereo fusion.
- Body motion violates the static-scene assumption. A moving/deforming thigh can produce incorrect geometry even if camera registration appears successful.
- Weakly textured skin, reflections, changing illumination, occlusions, and segmentation boundary errors can cause holes or incorrect area.
- Ball Pivoting does not guarantee a watertight mesh. This is intentional: capping an open patch adds artificial geometry and area.
- Inspect point clouds, mesh boundaries and connected components before accepting measurements.
- Validate on known curved surfaces with independently measured patch areas before any medical research use. Clinical validation and clinician oversight are necessary.

## Troubleshooting

**COLMAP not found:** install it, add it to PATH, or set `colmap_executable`.

**No sparse model:** improve overlap, sharpness, lighting and texture; ensure the subject is static; inspect COLMAP logs.

**Masks missing or wrong size:** create masks from `data/colmap_output/dense/images/`; match filename stems exactly.

**No depth maps:** inspect PatchMatch logs and ensure the dense workspace contains `images/` and `sparse/`. Dense stereo can need substantial memory.

**No points survive:** check masks and depth maps; temporarily set `min_views: 1` to diagnose; slightly relax depth tolerance only after inspecting the data.

**No mesh:** improve point density/coverage, adjust `bpa_radii_multipliers`, and inspect the cloud in CloudCompare.

Debug in order: sparse camera registration → undistorted images/masks → depth maps → raw points → filtered points → mesh. Do not tune meshing to compensate for bad camera geometry.

## References

- COLMAP: https://colmap.github.io/
- COLMAP CLI: https://colmap.github.io/cli.html
- Open3D: https://www.open3d.org/docs/
- Trimesh: https://trimesh.org/


### Scale note

The exported point cloud remains in COLMAP reconstruction units. If `cm_per_colmap_unit` is configured, the exported mesh is scaled to centimetres and the JSON area is in cm². The scale must be independently calibrated; it is not inferred automatically.
