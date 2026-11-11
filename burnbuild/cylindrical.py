import numpy as np
import open3d as o3d


def fit_cylinder(points):
    points = np.asarray(points, dtype=float)
    if len(points) < 20:
        raise ValueError("At least 20 points are required to fit a cylinder.")
    center = points.mean(axis=0)
    _, _, vh = np.linalg.svd(points - center, full_matrices=False)
    candidates = []
    for axis in vh:
        axis /= np.linalg.norm(axis)
        basis = np.linalg.svd(np.eye(3) - np.outer(axis, axis))[2][:2]
        coords = (points - center) @ basis.T
        design = np.c_[coords[:, 0], coords[:, 1], np.ones(len(coords))]
        rhs = -(coords[:, 0] ** 2 + coords[:, 1] ** 2)
        d, e, f = np.linalg.lstsq(design, rhs, rcond=None)[0]
        radial_center = np.array([-d / 2, -e / 2])
        radius_squared = float(np.dot(radial_center, radial_center) - f)
        if radius_squared <= 0:
            continue
        radius = float(np.sqrt(radius_squared))
        radial = coords - radial_center
        residual = np.abs(np.linalg.norm(radial, axis=1) - radius)
        candidates.append((np.percentile(residual, 95), axis.copy(), basis,
                           radial_center, radius, residual))
    if not candidates:
        raise ValueError("Could not estimate a positive cylinder radius.")
    _, axis, basis, radial_center, radius, residual = min(candidates, key=lambda x: x[0])
    if axis[0] < 0:
        axis = -axis
    origin = center + radial_center @ basis
    return {
        "origin": origin,
        "axis": axis,
        "basis": basis,
        "radius": radius,
        "residual_median": float(np.median(residual)),
        "residual_p95": float(np.percentile(residual, 95)),
    }


def _unwrap_angles(theta):
    theta = np.mod(theta, 2 * np.pi)
    ordered = np.sort(theta)
    gaps = np.diff(np.r_[ordered, ordered[0] + 2 * np.pi])
    start = ordered[(np.argmax(gaps) + 1) % len(ordered)]
    return np.mod(theta - start, 2 * np.pi), start


def create_cylinder_mesh(points, model, axial_resolution=160, angular_resolution=160):
    points = np.asarray(points, dtype=float)
    origin, axis, basis = model["origin"], model["axis"], model["basis"]
    q = points - origin
    axial = q @ axis
    radial = q @ basis.T
    theta, theta_start = _unwrap_angles(np.arctan2(radial[:, 1], radial[:, 0]))
    s0, s1 = np.percentile(axial, [1, 99])
    t0, t1 = np.percentile(theta, [1, 99])
    if s1 <= s0 or t1 <= t0:
        raise ValueError("Cylinder coordinates do not span a measurable patch.")
    ns = max(8, int(axial_resolution))
    nt = max(8, int(angular_resolution))
    ss = np.linspace(s0, s1, ns)
    tt = np.linspace(t0, t1, nt)
    grid_s, grid_t = np.meshgrid(ss, tt, indexing="ij")
    radial_xy = model["radius"] * np.stack(
        (np.cos(grid_t + theta_start), np.sin(grid_t + theta_start)), axis=-1)
    vertices = (origin + grid_s[..., None] * axis
                + radial_xy[..., 0, None] * basis[0]
                + radial_xy[..., 1, None] * basis[1]).reshape(-1, 3)
    rows = np.arange(ns - 1)[:, None]
    cols = np.arange(nt - 1)[None, :]
    i = rows * nt + cols
    faces = np.stack((i, i + 1, i + nt,
                      i + 1, i + nt + 1, i + nt), axis=-1).reshape(-1, 3)
    mesh = o3d.geometry.TriangleMesh()
    mesh.vertices = o3d.utility.Vector3dVector(vertices)
    mesh.triangles = o3d.utility.Vector3iVector(faces)
    mesh.compute_vertex_normals()
    return mesh
