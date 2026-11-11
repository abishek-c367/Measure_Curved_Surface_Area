## Read the whole project files and understand the project
## Read Experiments.md and experiment_state.json to know what has already been tried.

## Better accuracy strategies

The next implementation should use a **shared reference/small ratio**, not
independent absolute reconstructions:

1. Keep the 11 manual reference and small masks authoritative.
2. Use Canny/Hough/flow masks only as proposals for review, never as silent
   replacements.
3. Fit one cylinder to the union of the reference and small-region points
   using robust outlier rejection.
4. Project both regions onto that same cylinder and compute their areas in
   COLMAP units.
5. Report the ratio:

   `A_small_cm2 = (A_small_units / A_reference_units) * 56.25`

   The arbitrary COLMAP scale cancels completely.
6. Use per-view or leave-one-view-out estimates and report the median plus
   spread. A frame that changes the estimate substantially should be rejected
   with a diagnostic, not hidden by adding more propagated masks.
7. Use subpixel corner refinement (`cornerSubPix`) on the manually reviewed
   boundaries and fit the four sides jointly across anchor views.
8. Use a robust rectangle/cylinder intersection rather than percentile-clipping
   the point-cloud extents. Percentile clipping currently changes the measured
   patch dimensions when masks contain small boundary errors.

This approach directly targets the observed error: the numerator and
calibration denominator share camera, cylinder, and depth biases, so their
ratio is more stable than two separately fitted meshes.

## Further options if sub-percent accuracy is required

- Add manual corner annotations for every 10th–20th frame and interpolate a
  homography only between nearby reviewed anchors.
- Use a calibrated planar/cylindrical target with known corner coordinates to
  estimate camera scale and validate the reconstruction independently.
- Replace image-only optical flow with feature matching plus a homography
  constrained by four reviewed corners.
- Estimate a single global cylinder from all valid reference views, then hold
  its axis and radius fixed while measuring the small patch.
- Treat the four rectangle sides as observations with uncertainty and optimize
  corners, cylinder parameters, and projected edge alignment jointly.


## Research papers and publications only when needed for a concrete next
## experiment. Keep each turn bounded.
## Think harder to get a new perspective.

No automatic method should be called an **accuracy improvement** until it beats
the 3.9814 cm² baseline on the known 4.0 cm² target.

#**Instructions for the Agent**
# The experiment loop
1. Run exactly one experiment with one idea and compute the measured area.
   Determine the accuracy improvement and add a brief summary to Experiments.md.

2. Update experiment_state.json atomically with status, result, error,
   next_idea, and best result.
3. End the turn after the checkpoint. An external controller starts the next
   turn in a fresh session.
4. Do not repeat completed or failed experiments.
5. Keep each process below **30 GB of RAM** and avoid large generated files.


The idea is that you are a completely autonomous researcher trying things out. If they work, keep. If they don't, discard. And you're advancing the branch so that you can iterate. If you feel like you're getting stuck in some way, you can rewind but you should probably do this very very sparingly (if ever).

Crashes: If a run crashes (OOM, or a bug, or etc.), use your judgment: If it's something dumb and easy to fix (e.g. a typo, a missing import), fix it and re-run. If the idea itself is fundamentally broken, just skip it, log "crash" as the status in the tsv, and move on.

Never attempt to continue indefinitely inside one conversation context. The
external controller provides continuity by starting a fresh session per turn.
If the context is large, write the checkpoint and stop cleanly.