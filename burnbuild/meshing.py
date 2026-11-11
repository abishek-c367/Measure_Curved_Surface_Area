from pathlib import Path
import numpy as np
import open3d as o3d
from .pointcloud import point_spacing


def select_triangles(mesh, indices):
    faces = np.asarray(mesh.triangles)[np.asarray(indices, dtype=int)]
    if not len(faces):
        raise ValueError("Triangle selection is empty.")
    used, inverse = np.unique(faces, return_inverse=True)
    result = o3d.geometry.TriangleMesh()
    result.vertices = o3d.utility.Vector3dVector(np.asarray(mesh.vertices)[used])
    result.triangles = o3d.utility.Vector3iVector(inverse.reshape(-1, 3))
    return result


def keep_mask_supported_triangles(mesh, views, min_views=1):
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.triangles)
    if not len(faces):
        return mesh
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    samples = np.stack((a, b, c, (a + b) / 2, (b + c) / 2,
                        (c + a) / 2, (a + b + c) / 3), axis=1)
    support = np.zeros(len(faces), dtype=np.uint16)
    for view in views:
        flat = samples.reshape(-1, 3)
        pc = (view["R"] @ flat.T + np.asarray(view["t"]).reshape(3, 1)).T
        z = pc[:, 2]
        uvw = (view["K"] @ pc.T).T
        valid = z > 1e-8
        uv = np.full((len(flat), 2), np.nan)
        uv[valid] = uvw[valid, :2] / uvw[valid, 2:3]
        h, w = view["mask"].shape
        x = np.rint(uv[:, 0]).astype(int)
        y = np.rint(uv[:, 1]).astype(int)
        inside = valid & (x >= 0) & (x < w) & (y >= 0) & (y < h)
        inside &= np.where(inside, view["mask"][np.clip(y, 0, h - 1),
                                                np.clip(x, 0, w - 1)], False)
        support += inside.reshape(-1, 7).all(axis=1)
    keep = support >= int(min_views)
    if not np.any(keep):
        raise ValueError("Foreground mask rejected every mesh triangle.")
    return select_triangles(mesh, np.where(keep)[0])


def largest_components(mesh, min_faces=20):
    faces = np.asarray(mesh.triangles)
    vertex_faces = {}
    for fi, face in enumerate(faces):
        for v in face:
            vertex_faces.setdefault(int(v), []).append(fi)
    adjacency = [set() for _ in range(len(faces))]
    for group in vertex_faces.values():
        for i in group:
            adjacency[i].update(group)
    seen = np.zeros(len(faces), dtype=bool)
    comps = []
    for start in range(len(faces)):
        if seen[start]:
            continue
        stack, comp = [start], []
        seen[start] = True
        while stack:
            i = stack.pop()
            comp.append(i)
            for j in adjacency[i]:
                if not seen[j]:
                    seen[j] = True
                    stack.append(j)
        comps.append(comp)
    keep = [i for c in comps if len(c) >= min_faces for i in c]
    if not keep:
        keep = max(comps, key=len)
    return select_triangles(mesh, keep)


def create_mesh(cloud, multipliers, remove_components=True, min_faces=20):
    if len(cloud.points) < 20:
        raise ValueError("Too few points for surface reconstruction.")
    cloud = o3d.geometry.PointCloud(cloud)
    spacing = point_spacing(cloud)
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(
        radius=max(spacing * 4, 1e-8), max_nn=30))
    cloud.orient_normals_consistent_tangent_plane(30)
    radii = o3d.utility.DoubleVector([spacing * float(x) for x in multipliers])
    mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(cloud, radii)
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_triangles()
    mesh.remove_duplicated_vertices()
    mesh.remove_non_manifold_edges()
    mesh.remove_unreferenced_vertices()
    if len(mesh.triangles) == 0:
        raise ValueError("Ball Pivoting produced no faces. Improve point density or tune BPA radii.")
    if remove_components:
        mesh = largest_components(mesh, min_faces)
    mesh.compute_vertex_normals()
    return mesh


def area(mesh):
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
    if not len(f):
        return 0.0
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float((0.5 * np.linalg.norm(np.cross(b-a, c-a), axis=1)).sum())


def export_mesh(mesh, ply, obj, scale=1.0):
    out = o3d.geometry.TriangleMesh(mesh)
    if scale != 1:
        out.scale(float(scale), center=(0, 0, 0))
    out.compute_vertex_normals()
    Path(ply).parent.mkdir(parents=True, exist_ok=True)
    Path(obj).parent.mkdir(parents=True, exist_ok=True)
    if not o3d.io.write_triangle_mesh(str(ply), out):
        raise RuntimeError(f"Failed to write {ply}")
    if not o3d.io.write_triangle_mesh(str(obj), out):
        raise RuntimeError(f"Failed to write {obj}")
    return out
