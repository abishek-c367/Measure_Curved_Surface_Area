import numpy as np
from .backproject import project


def filter_by_views(points, source_name, views, min_views=2, tolerance=0.03):
    if len(points) == 0:
        return points
    support = np.ones(len(points), dtype=np.uint16)  # source view supports its own points
    for view in views:
        if view["name"] == source_name:
            continue
        uv, z, front = project(points, view["K"], view["R"], view["t"])
        h, w = view["depth"].shape
        inside = front & np.isfinite(uv).all(axis=1)
        inside &= (uv[:, 0] >= 0) & (uv[:, 0] < w)
        inside &= (uv[:, 1] >= 0) & (uv[:, 1] < h)
        idx = np.where(inside)[0]
        if len(idx) == 0:
            continue
        x = np.rint(uv[idx, 0]).astype(int)
        y = np.rint(uv[idx, 1]).astype(int)
        rounded_inside = (x >= 0) & (x < w) & (y >= 0) & (y < h)
        idx = idx[rounded_inside]
        x = x[rounded_inside]
        y = y[rounded_inside]
        if len(idx) == 0:
            continue
        measured = view["depth"][y, x]
        good = view["mask"][y, x] & np.isfinite(measured) & (measured > 0)
        rel = np.abs(z[idx] - measured) / np.maximum(np.abs(measured), 1e-8)
        accepted = idx[good & (rel <= tolerance)]
        support[accepted] += 1
    return points[support >= min_views]
