Read `program.md`, `Experiments.md`, `experiment_state.json`, and the current
git status before doing anything.

Run exactly one experiment: the `next_idea` in `experiment_state.json`.

Rules:

- Never repeat an item in `completed` or `failed`.
- Keep every process below 30 GB RAM and avoid creating large generated files.
- Use existing artifacts and targeted commands; do not rerun full COLMAP unless
  the state explicitly requires it.
- Record the experiment, command, outcome, measured area, error versus 4.0 cm²,
  and whether it beats the current best in `Experiments.md`.
- Update `experiment_state.json` atomically. Set `current_experiment` while
  working, then append a concise result to `completed` or `failed`, update
  `best` only when the error improves, and set the next `next_idea`.
- If an experiment fails, record the failure and choose a different next idea.
- Do not push or modify unrelated files.
- End this turn after one experiment and a concise checkpoint summary. A later
  controller turn will continue the loop.
