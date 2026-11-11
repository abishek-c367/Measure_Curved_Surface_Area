import numpy as np
import open3d as o3d
from pathlib import Path


def make_cloud(points, voxel_size=0.0, neighbors=20, std_ratio=2.0):
    if points is None or len(points) == 0:
        raise ValueError("No burn points. Check masks, depth maps and view filtering.")
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.asarray(points, dtype=float))
    if voxel_size > 0:
        cloud = cloud.voxel_down_sample(float(voxel_size))
    if len(cloud.points) > neighbors + 1:
        cloud, _ = cloud.remove_statistical_outlier(nb_neighbors=int(neighbors),
                                                   std_ratio=float(std_ratio))
    if len(cloud.points) == 0:
        raise ValueError("Point-cloud cleanup removed every point.")
    return cloud


def save_cloud(cloud, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if not o3d.io.write_point_cloud(str(path), cloud):
        raise RuntimeError(f"Could not write point cloud {path}")


def point_spacing(cloud):
    d = np.asarray(cloud.compute_nearest_neighbor_distance())
    d = d[np.isfinite(d) & (d > 0)]
    if not len(d):
        raise ValueError("Cannot estimate point spacing.")
    return float(np.median(d))
