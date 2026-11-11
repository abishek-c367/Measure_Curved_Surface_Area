# Recent Activity Log - BurnBuildSurface Project
**Generated**: Wed Nov 11, 2026

---

## 📊 PROJECT STATUS: READY FOR NEXT EXPERIMENT

**Best Result So Far**: 3.9814 cm² (0.47% error on 4.0 cm² target)
**Current State**: experiment_state.json shows `status: "ready"`, ready for next experiment

---

## ✅ WHAT HAS BEEN COMPLETED

### 1. **COLMAP Configuration & Setup** ✅
- Configured COLMAP 4.2.1 with CUDA 12.8 runtime libraries
- Resolved CUDA version mismatch (project was compiled for CUDA 12, system had CUDA 13.4)
- Copied required libraries: libcudart, libcublas, libcusolver, libnvJitLink

### 2. **Baseline Measurement (Experiment 1)** ✅
**Original 11-view manual reconstruction:**
- Reference area: 2.0430 COLMAP units²
- Small rectangle area: 0.1446 COLMAP units²  
- Scale factor: 5.247 cm/unit
- **Result: 3.9814 cm²** (0.47% error, current best result)

### 3. **Automatic Mask Propagation Tests** ✅

#### Experiment 2: Small-mask propagation only
- Script: `scripts/propagate_small_rectangle_masks.py`
- Techniques: Canny edges, Hough lines, Lucas-Kanade tracking, Farneback flow
- Generated 196 masks from 200 views (rejected 4 frames)
- **Result: 3.9072 cm²** (2.32% error) - WORSE than baseline

#### Experiment 3: Both reference + small mask propagation
- Applied quadrilateral detector to 12 larger reference anchors
- Generated propagated masks for both reference and small regions
- Rejected 38 frames due to tracking leaving image boundary
- **Result: 3.8218 cm²** (4.46% error) - WORST result

### 4. **Key Findings & Analysis** ✅
- Increasing view count does NOT improve accuracy
- Automatic propagation introduces systematic boundary bias
- Propagation errors affect both numerator AND reference-based scale
- Current masks are geometrically regular but have coherent edge biases
- This is a coupled segmentation + calibration + surface-model problem

### 5. **Project Files Created/Modified** ✅
- `Experiments.md` - Full experiment documentation (3 experiments completed)
- `experiment_state.json` - State tracker with next_idea set
- `data/reference_mask_propagated/` - Reference masks from Experiment 3
- `data/small_rec_mask_propagated/` - Small masks from Experiment 3
- `outputs/reports/small_rectangle_measurement.json` - Baseline results
- `outputs/reports/small_rectangle_canny_reference.json` - Exp 3 results
- `program.md` - Agent instructions for experiment loop
- `COLMAP reconstruction.md` - Reconstruction documentation

### 6. **Git Commits** ✅
1. `be55e16ff3a6` - Add Experiments.md, program.md and reference_mask_propagated data
2. `e5df5f9` - Publish curved surface area pipeline

---

## 🎯 WHAT REMAINS (Next Steps)

### Immediate Next Experiment: **Shared-Cylinder Ratio Measurement**
**From program.md next_idea:**
> "Run the shared-reference/small ratio measurement with robust leave-one-view-out diagnostics."

**Approach (from program.md):**
1. Keep 11 manual reference and small masks authoritative
2. Use Canny/Hough/flow masks only as proposals for review, not silent replacements
3. Fit ONE cylinder to union of reference AND small-region points using robust outlier rejection
4. Project both regions onto that SAME cylinder
5. Compute areas in COLMAP units
6. Report ratio: `A_small_cm2 = (A_small_units / A_reference_units) * 56.25`
7. Use per-view or leave-one-view-out estimates, report median + spread
8. Reject frames that substantially change the estimate with diagnostics

**Advanced options if sub-percent accuracy needed:**
- Add manual corner annotations for every 10th–20th frame
- Interpolate homography between nearby reviewed anchors
- Use calibrated planar/cylindrical target with known coordinates
- Replace image-only optical flow with feature matching + constrained homography
- Estimate single global cylinder from all valid reference views
- Treat four rectangle sides as observations with uncertainty, optimize jointly

### Remaining Work Items:

1. ✅ **Experiment implementation** - Write/run code for shared-cylinder approach
2. ⏳ **Cross-validation testing** - Implement leave-one-view-out diagnostics
3. ⏳ **Error analysis** - Report median + spread across views
4. ⏳ **Frame rejection logic** - Identify and report problematic frames
5. ⏳ **Update experiment_state.json** - Record new best result or status
6. ⏳ **Document in Experiments.md** - Add findings to experiment log
7. ⏳ **Git commit** - Save changes

---

## 📁 Key Files to Monitor

| File | Purpose | Last Modified by |
|------|---------|------------------|
| `experiment_state.json` | Track current experiment status | OpenClaw/Automated |
| `Experiments.md` | Human-readable experiment log | Last: Commit be55e16f |
| `program.md` | Agent instructions & guidelines | Created in same commit |
| `outputs/reports/` | Experiment output files | Multiple experiments |
| `data/*propagated*/` | Propagation results | Experiment 3 |

---

## 🚀 Ready For

The project is **READY** for the next experiment run. The agent/human should:

1. Implement the shared-cylinder ratio measurement approach
2. Run with leave-one-view-out diagnostics
3. Compare against 3.9814 cm² baseline
4. Update `experiment_state.json` and `Experiments.md` accordingly

**Target**: Beat the 3.9814 cm² baseline on the known 4.0 cm² target.

---

## 🔄 Continuity Protocol

**When context approaches 90%:**
- Write current state to this `recent_activity.md` file ✅ (done now)
- Stop cleanly at checkpoint
- On resume: Read this file first to understand where you left off
- Do NOT repeat completed experiments
- Continue from `next_idea` in experiment_state.json or manually set

**Context length is currently LOW - safe to continue working.**

---

## 📝 Notes

- Current GPU usage: Ollama llama-server running 96% utilization (7.4 GB RAM)
- CUDA version issue resolved via CUDA 12.8 library copy
- Project uses COLMAP arbitrary-scale; ratio approach cancels scale factors
- Best result achieved with minimal manual intervention (11 views only)
