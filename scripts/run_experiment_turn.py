"""Run one bounded OpenClaw experiment turn with persistent checkpointing."""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--session-prefix", default="experiment-loop")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    project = args.project.resolve()
    state_path = project / "experiment_state.json"
    prompt_path = project / "experiment_turn_prompt.md"
    lock_path = project / ".experiment-loop.lock"
    log_dir = project / "experiment_logs"
    log_dir.mkdir(exist_ok=True)

    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another experiment turn is already running.")
            return 0

        state = load_json(state_path)
        if state.get("status") == "stopped":
            print("Experiment loop is stopped in experiment_state.json.")
            return 0
        if args.dry_run:
            print(json.dumps({"session_key": args.session_prefix, "state": state}, indent=2))
            return 0
        state["status"] = "running"
        state["controller_runs"] = int(state.get("controller_runs", 0)) + 1
        state["last_turn"] = {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pid": os.getpid(),
        }
        write_json_atomic(state_path, state)

        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        session_key = f"agent:main:{args.session_prefix}-{timestamp}"
        log_path = log_dir / f"{timestamp}.log"
        command = [
            "openclaw",
            "agent",
            "--session-key",
            session_key,
            "--message-file",
            str(prompt_path),
            "--timeout",
            str(args.timeout),
            "--json",
        ]
        try:
            with log_path.open("w", encoding="utf-8") as output:
                output.write("$ " + " ".join(command) + "\n")
                output.flush()
                result = subprocess.run(
                    command,
                    cwd=project,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=args.timeout + 60,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            state = load_json(state_path)
            state["status"] = "ready"
            state["last_turn"]["finished_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            state["last_turn"]["exit_code"] = 124
            state["last_turn"]["error"] = "OpenClaw turn exceeded controller timeout."
            state["last_turn"]["log"] = str(log_path.relative_to(project))
            write_json_atomic(state_path, state)
            print(json.dumps(state["last_turn"], indent=2))
            return 124
        state = load_json(state_path)
        state["last_turn"]["finished_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        state["last_turn"]["exit_code"] = result.returncode
        state["last_turn"]["log"] = str(log_path.relative_to(project))
        if result.returncode != 0:
            state["status"] = "ready"
            state["last_turn"]["error"] = "OpenClaw turn failed; inspect the log."
        else:
            state["status"] = "ready"
        write_json_atomic(state_path, state)
        print(json.dumps(state["last_turn"], indent=2))
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
