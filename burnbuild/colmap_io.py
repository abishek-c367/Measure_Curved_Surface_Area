from dataclasses import dataclass
from pathlib import Path
import numpy as np


@dataclass
class Camera:
    camera_id: int
    model: str
    width: int
    height: int
    params: np.ndarray

    def K(self):
        p = self.params
        if self.model == "SIMPLE_PINHOLE":
            f, cx, cy = p[:3]
            return np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], float)
        if self.model == "PINHOLE":
            fx, fy, cx, cy = p[:4]
            return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], float)
        raise ValueError(
            f"Unsupported dense camera model {self.model}; expected PINHOLE or SIMPLE_PINHOLE."
        )


@dataclass
class Pose:
    image_id: int
    qvec: np.ndarray
    tvec: np.ndarray
    camera_id: int
    name: str

    def R(self):
        w, x, y, z = self.qvec
        return np.array([
            [1-2*y*y-2*z*z, 2*x*y-2*z*w, 2*x*z+2*y*w],
            [2*x*y+2*z*w, 1-2*x*x-2*z*z, 2*y*z-2*x*w],
            [2*x*z-2*y*w, 2*y*z+2*x*w, 1-2*x*x-2*y*y],
        ], dtype=float)


def read_cameras(path):
    result = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split()
        result[int(p[0])] = Camera(int(p[0]), p[1], int(p[2]), int(p[3]),
                                   np.asarray([float(x) for x in p[4:]], float))
    return result


def read_poses(path):
    lines = [x.rstrip() for x in Path(path).read_text(encoding="utf-8").splitlines()
             if x.strip() and not x.lstrip().startswith("#")]
    result = {}
    i = 0
    while i < len(lines):
        p = lines[i].split()
        if len(p) < 10:
            raise ValueError(f"Malformed COLMAP image record: {lines[i]}")
        name = " ".join(p[9:])
        result[name] = Pose(int(p[0]), np.asarray([float(x) for x in p[1:5]]),
                            np.asarray([float(x) for x in p[5:8]]), int(p[8]), name)
        i += 2  # COLMAP TXT format stores 2D observations on the next line.
    return result


def find_txt_model(folder):
    folder = Path(folder)
    candidates = [p for p in folder.iterdir()
                  if p.is_dir() and (p / "cameras.txt").exists()
                  and (p / "images.txt").exists()]
    if not candidates:
        raise FileNotFoundError(f"No COLMAP TXT model found under {folder}")
    return max(candidates, key=lambda p: sum(
        1 for line in (p / "images.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        and len(line.split()) >= 10
    ))
