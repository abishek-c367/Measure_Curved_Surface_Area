from pathlib import Path
import numpy as np


def read_colmap_array(path):
    """Read COLMAP's width&height&channels& float32 array format."""
    with Path(path).open("rb") as f:
        header = b""
        count = 0
        while count < 3:
            c = f.read(1)
            if not c:
                raise ValueError(f"Invalid COLMAP array header: {path}")
            header += c
            if c == b"&":
                count += 1
        width, height, channels = [int(x) for x in header.decode("ascii").strip("&").split("&")]
        data = np.fromfile(f, dtype=np.float32)
    expected = width * height * channels
    if data.size != expected:
        raise ValueError(f"Depth data size mismatch: {path}")
    arr = data.reshape((width, height, channels), order="F").transpose(1, 0, 2)
    return arr[:, :, 0] if channels == 1 else arr


def find_depth_file(folder, image_name):
    folder = Path(folder)
    stem = Path(image_name).stem
    for p in [folder / f"{image_name}.geometric.bin",
              folder / f"{stem}.geometric.bin",
              folder / f"{image_name}.photometric.bin",
              folder / f"{stem}.photometric.bin"]:
        if p.exists():
            return p
    raise FileNotFoundError(f"No depth map for {image_name} in {folder}")
