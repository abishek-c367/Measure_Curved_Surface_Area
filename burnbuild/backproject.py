import numpy as np


def backproject(depth, mask, K, R, t, max_points=0, rng=None):
    valid = mask & np.isfinite(depth) & (depth > 0)
    v, u = np.where(valid)
    if max_points and len(u) > max_points:
        rng = rng or np.random.default_rng(42)
        ids = rng.choice(len(u), int(max_points), replace=False)
        u, v = u[ids], v[ids]
    if len(u) == 0:
        return np.empty((0, 3), dtype=float)
    pix = np.vstack((u, v, np.ones_like(u))).astype(float)
    pc = (np.linalg.inv(K) @ pix) * depth[v, u][None, :]
    return (R.T @ (pc - np.asarray(t).reshape(3, 1))).T


def project(points, K, R, t):
    pc = (R @ points.T + np.asarray(t).reshape(3, 1)).T
    z = pc[:, 2]
    valid = z > 1e-8
    uvw = (K @ pc.T).T
    uv = np.full((len(points), 2), np.nan)
    uv[valid] = uvw[valid, :2] / uvw[valid, 2:3]
    return uv, z, valid
