from pathlib import Path
from datetime import datetime, timezone
import json
from .meshing import area


def write_report(mesh, path, cm_per_unit=None, points=None, images=None, settings=None):
    raw = area(mesh)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "surface_area": raw,
        "area_unit": "cm^2" if cm_per_unit is not None else "COLMAP_units^2 (arbitrary scale)",
        "surface_area_cm2": raw if cm_per_unit is not None else None,
        "scale_cm_per_colmap_unit": cm_per_unit,
        "vertex_count": int(len(mesh.vertices)),
        "triangle_count": int(len(mesh.triangles)),
        "burn_point_count": points,
        "registered_image_count": images,
        "is_open_surface_patch": True,
        "clinical_validation": "not clinically validated",
        "settings": settings or {},
    }
    if cm_per_unit is not None:
        # mesh has already been scaled to centimetres before this report is written.
        report["surface_area_cm2"] = raw
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
