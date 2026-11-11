import logging
import subprocess

log = logging.getLogger(__name__)


class ColmapRunner:
    def __init__(self, executable):
        self.executable = str(executable)

    def run(self, subcommand, args):
        cmd = [self.executable, subcommand] + [str(x) for x in args]
        log.info("COLMAP: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except FileNotFoundError as e:
            raise RuntimeError(
                f"COLMAP executable '{self.executable}' not found. Install COLMAP, "
                "add it to PATH, or edit config.yaml."
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"COLMAP command '{subcommand}' failed with exit code {e.returncode}."
            ) from e
