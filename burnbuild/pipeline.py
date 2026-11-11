from pathlib import Path
import logging
import cv2
import numpy as np
import open3d as o3d

from .colmap_runner import ColmapRunner
from .colmap_io import read_cameras, read_poses, find_txt_model
from .depth_io import read_colmap_array, find_depth_file
from .masks import find_mask, load_mask, validate_masks
from .backproject import backproject
from .multiview import filter_by_views
from .pointcloud import make_cloud, save_cloud
from .meshing import create_mesh, export_mesh, keep_mask_supported_triangles
from .cylindrical import fit_cylinder, create_cylinder_mesh
from .measurement import write_report

log = logging.getLogger(__name__)


class BurnBuildPipeline:
    def __init__(self, cfg):
        self.cfg = cfg
        self.p = cfg["paths"]
        self.cc = cfg["colmap"]
        self.rc = cfg["reconstruction"]
        self.mc = cfg["meshing"]
        self.runner = ColmapRunner(self.cc["colmap_executable"])

    def _dirs(self):
        for k, v in self.p.items():
            Path(v).parent.mkdir(parents=True, exist_ok=True)
        for k in ["images_dir", "masks_dir", "workspace_dir", "sparse_dir", "dense_dir",
                  "output_pointcloud_dir", "output_mesh_dir", "output_reports_dir"]:
            Path(self.p[k]).mkdir(parents=True, exist_ok=True)

    def prepare(self):
        self._dirs()
        image_dir = Path(self.p["images_dir"])
        imgs = [x for x in image_dir.iterdir() if x.suffix.lower() in
                {".jpg", ".jpeg", ".png", ".tif", ".tiff"}]
        if len(imgs) < 2:
            raise RuntimeError(f"Add at least two source images to {image_dir}")
        db = Path(self.p["database_path"])
        if db.exists():
            db.unlink()
        common = ["--database_path", db, "--image_path", image_dir,
                  "--ImageReader.camera_model", self.cc["camera_model"],
                  "--ImageReader.single_camera", str(self.cc["single_camera"]).lower()]
        self.runner.run("feature_extractor", common)
        matcher = "sequential_matcher" if self.cc["matcher"] == "sequential" else "exhaustive_matcher"
        self.runner.run(matcher, ["--database_path", db,
                                  "--FeatureMatching.use_gpu", str(self.cc["use_gpu"]).lower()])
        sparse = Path(self.p["sparse_dir"])
        self.runner.run("mapper", ["--database_path", db, "--image_path", image_dir,
                                   "--output_path", sparse])
        binary = [x for x in sparse.iterdir() if x.is_dir() and (x / "images.bin").exists()]
        if not binary:
            raise RuntimeError("COLMAP mapper produced no sparse model.")
        model = max(binary, key=lambda x: (x / "images.bin").stat().st_size)
        txt = model / "txt"
        txt.mkdir(exist_ok=True)
        self.runner.run("model_converter", ["--input_path", model, "--output_path", txt,
                                            "--output_type", "TXT"])
        dense = Path(self.p["dense_dir"])
        self.runner.run("image_undistorter", ["--image_path", image_dir, "--input_path", model,
                                              "--output_path", dense, "--output_type", "COLMAP",
                                              "--max_image_size", self.cc["max_image_size"]])
        # Convert the undistorted dense model too: its intrinsics/poses correspond
        # to dense/images and must be used with the PatchMatch depth maps.
        dense_sparse = dense / "sparse"
        dense_txt = dense_sparse / "txt"
        dense_txt.mkdir(parents=True, exist_ok=True)
        self.runner.run("model_converter", ["--input_path", dense_sparse,
                                            "--output_path", dense_txt,
                                            "--output_type", "TXT"])
        log.info("Prepare complete. Manually segment images in %s and save masks in %s",
                 dense / "images", self.p["masks_dir"])

    def _model(self):
        return find_txt_model(Path(self.p["dense_dir"]) / "sparse")

    def _patchmatch(self):
        dense = Path(self.p["dense_dir"])
        self.runner.run("patch_match_stereo", [
            "--workspace_path", dense, "--workspace_format", "COLMAP",
            "--PatchMatchStereo.geom_consistency", str(self.cc["geom_consistency"]).lower(),
            "--PatchMatchStereo.window_radius", self.cc["window_radius"],
            "--PatchMatchStereo.window_step", self.cc["window_step"],
            "--PatchMatchStereo.num_samples", self.cc["num_samples"],
            "--PatchMatchStereo.num_iterations", self.cc["num_iterations"],
        ])

    def reconstruct(self):
        self._dirs()
        dense = Path(self.p["dense_dir"])
        images_dir = dense / "images"
        model = self._model()
        check = validate_masks(images_dir, self.p["masks_dir"])
        if check["missing"] or check["empty"] or check["mismatched"]:
            raise RuntimeError(f"Mask validation failed: {check}. Masks must match undistorted images.")
        self._patchmatch()

        cameras = read_cameras(model / "cameras.txt")
        poses = read_poses(model / "images.txt")
        depth_dir = dense / "stereo" / "depth_maps"
        views, rng = [], np.random.default_rng(42)

        for name, pose in poses.items():
            if pose.camera_id not in cameras:
                log.warning("No camera record for %s", name)
                continue
            camera = cameras[pose.camera_id]
            depth = read_colmap_array(find_depth_file(depth_dir, name))
            mask_path = find_mask(self.p["masks_dir"], name)
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                continue
            image = cv2.imread(str(images_dir / name), cv2.IMREAD_GRAYSCALE)
            if image is None:
                log.warning("Missing undistorted image %s", name)
                continue
            if mask.shape != image.shape:
                raise ValueError(f"Mask dimensions do not match undistorted image: {name}")
            if depth.shape != image.shape:
                mask = cv2.resize(mask, (depth.shape[1], depth.shape[0]),
                                  interpolation=cv2.INTER_NEAREST)
                sx, sy = depth.shape[1] / image.shape[1], depth.shape[0] / image.shape[0]
                K = camera.K()
                K[0, :] *= sx
                K[1, :] *= sy
            else:
                K = camera.K()
            views.append({"name": name, "K": K, "R": pose.R(), "t": pose.tvec,
                          "depth": depth, "mask": mask > 0})

        if len(views) < 2:
            raise RuntimeError("Fewer than two registered images have usable depth/masks.")

        point_sets = []
        for src in views:
            pts = backproject(src["depth"], src["mask"], src["K"], src["R"], src["t"],
                              int(self.rc["max_points_per_image"]), rng)
            log.info("%s: %d candidate points", src["name"], len(pts))
            kept = filter_by_views(pts, src["name"], views,
                                   int(self.rc["min_views"]),
                                   float(self.rc["depth_relative_tolerance"]))
            log.info("%s: %d points after cross-view filter", src["name"], len(kept))
            if len(kept):
                point_sets.append(kept)
        if not point_sets:
            raise RuntimeError("No points survived. Check masks/depth; try min_views=1 to diagnose.")
        points = np.vstack(point_sets)
        cloud = make_cloud(points, float(self.rc["voxel_size"]),
                           int(self.rc["statistical_outlier_neighbors"]),
                           float(self.rc["statistical_outlier_std_ratio"]))
        pc_path = Path(self.p["output_pointcloud_dir"]) / "burn_points.ply"
        save_cloud(cloud, pc_path)

        foreground_min_views = int(self.mc.get("foreground_min_views", 1))
        surface_model = self.mc.get("surface_model", "bpa")
        selected_radii = None
        cylinder = None
        if surface_model == "cylindrical":
            cylinder = fit_cylinder(np.asarray(cloud.points))
            log.info("Cylinder fit radius=%g, median residual=%g, p95 residual=%g",
                     cylinder["radius"], cylinder["residual_median"],
                     cylinder["residual_p95"])
            mesh = create_cylinder_mesh(
                np.asarray(cloud.points), cylinder,
                int(self.mc.get("cylinder_axial_resolution", 160)),
                int(self.mc.get("cylinder_angular_resolution", 160)))
            mesh = keep_mask_supported_triangles(mesh, views, foreground_min_views)
        elif surface_model == "bpa":
            radii_candidates = [self.mc["bpa_radii_multipliers"],
                                [1.0, 1.5, 2.0],
                                [0.75, 1.25, 1.75]]
            mesh = None
            for radii in radii_candidates:
                try:
                    candidate = create_mesh(
                        cloud, radii,
                        bool(self.mc["remove_small_components"]),
                        int(self.mc["min_component_triangles"]))
                    candidate = keep_mask_supported_triangles(
                        candidate, views, foreground_min_views)
                    if len(candidate.triangles):
                        mesh = candidate
                        selected_radii = radii
                        log.info("Foreground-only mesh accepted with BPA radii %s", radii)
                        break
                except ValueError as exc:
                    log.warning("Mesh attempt with BPA radii %s rejected: %s", radii, exc)
        else:
            raise ValueError(f"Unsupported surface_model: {surface_model}")
        if mesh is None:
            raise RuntimeError(
                "Could not produce a mesh contained by the foreground masks. "
                "Check mask alignment and depth coverage.")
        cm_per_unit = self.cfg["measurement"].get("cm_per_colmap_unit")
        scale = float(cm_per_unit) if cm_per_unit is not None else 1.0
        mesh_ply = Path(self.p["output_mesh_dir"]) / "burn_surface.ply"
        mesh_obj = Path(self.p["output_mesh_dir"]) / "burn_surface.obj"
        scaled = export_mesh(mesh, mesh_ply, mesh_obj, scale)
        report_path = Path(self.p["output_reports_dir"]) / "measurement.json"
        report = write_report(scaled, report_path, cm_per_unit,
                              len(cloud.points), len(views),
                              {"min_views": self.rc["min_views"],
                               "depth_relative_tolerance": self.rc["depth_relative_tolerance"],
                               "voxel_size": self.rc["voxel_size"],
                              "surface_model": surface_model,
                              "bpa_radii_multipliers": selected_radii,
                              "foreground_min_views": foreground_min_views,
                              "cylinder_radius": None if cylinder is None else cylinder["radius"],
                              "cylinder_residual_median": (
                                  None if cylinder is None else cylinder["residual_median"]),
                              "cylinder_residual_p95": (
                                  None if cylinder is None else cylinder["residual_p95"])})
        log.info("Finished. Point cloud: %s", pc_path)
        log.info("Mesh: %s and %s", mesh_ply, mesh_obj)
        log.info("Area: %s %s", report["surface_area"], report["area_unit"])

    def visualize(self):
        mesh = Path(self.p["output_mesh_dir"]) / "burn_surface.ply"
        cloud = Path(self.p["output_pointcloud_dir"]) / "burn_points.ply"
        if mesh.exists():
            geom = o3d.io.read_triangle_mesh(str(mesh))
        elif cloud.exists():
            geom = o3d.io.read_point_cloud(str(cloud))
        else:
            raise FileNotFoundError("Run reconstruct before visualize.")
        o3d.visualization.draw_geometries([geom], window_name="BurnBuildSurface")
