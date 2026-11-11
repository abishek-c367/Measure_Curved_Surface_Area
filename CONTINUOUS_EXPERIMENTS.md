# Continuous experiment loop

The project now supports bounded OpenClaw turns instead of one unbounded
conversation. Each turn runs one experiment, writes a checkpoint, and exits.
The next turn uses a fresh session, so the previous transcript cannot fill the
context window.

## Files

- `experiment_state.json`: durable controller and experiment state.
- `experiment_turn_prompt.md`: short instructions sent on every turn.
- `scripts/run_experiment_turn.py`: lock, timeout, log, and OpenClaw launcher.
- `experiment_logs/`: ignored per-turn logs.

## Test one turn without starting OpenClaw

```bash
python scripts/run_experiment_turn.py --dry-run
```

## Run one real bounded turn

```bash
python scripts/run_experiment_turn.py --timeout 1800
```

The controller refuses overlapping turns, records a nonzero exit or timeout
in the checkpoint, and leaves the state resumable. The agent itself must update
`experiment_state.json` atomically after its one experiment.

## Schedule continuous execution

Use an external scheduler to invoke the controller every 30 minutes. For
OpenClaw's scheduler, create a **disabled** job first and enable it only after
the dry run and one manual turn have been reviewed:

```bash
openclaw cron add \
  --name curved-surface-experiment-loop \
  --every 30m \
  --command "cd /home/geninfolab/Abishek_Chaudhari/BurnBuildSurface && .venv/bin/python scripts/run_experiment_turn.py --timeout 1800" \
  --command-cwd /home/geninfolab/Abishek_Chaudhari/BurnBuildSurface \
  --timeout-seconds 1900 \
  --no-output-timeout-seconds 1900 \
  --output-max-bytes 200000 \
  --disabled
```

Then inspect and enable it:

```bash
openclaw cron list
openclaw cron enable <job-id>
```

Stop safely by setting `"status": "stopped"` in `experiment_state.json` or
disabling the job. The controller will not start a new turn while stopped.

The 30-minute interval is intentional: it leaves time for a 30-minute
experiment timeout, avoids overlapping work, and limits runaway retries.
