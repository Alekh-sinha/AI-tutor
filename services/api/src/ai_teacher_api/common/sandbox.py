"""A small shell sandbox for the harness experiment (bubblewrap): only the work folder is writable, nothing else of the machine is visible,
and there is NO network. The agent gets a shell and a file system, but only inside this box."""

import os
import subprocess
import sys
from pathlib import Path

VENV = Path(sys.prefix)  # the project venv: gives the sandbox python + Pillow, read-only
PYROOT = Path(os.path.realpath(sys.executable)).parent.parent  # the interpreter's own installation, read-only
MAX_OUT = 4000


def run_in_sandbox(command: str, workdir: Path, timeout: int = 60, network: bool = False) -> dict:
    """Run a shell command with `workdir` mounted writable at /work. Returns {"exit_code", "output"}."""
    argv = [
        "bwrap",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
        "--ro-bind", str(PYROOT), str(PYROOT), "--ro-bind", str(VENV), "/venv",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--bind", str(workdir.resolve()), "/work", "--chdir", "/work",
        *(["--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
           "--ro-bind", "/etc/ssl", "/etc/ssl"] if network else ["--unshare-all"]),  # network only when asked; never the host's files or credentials
        "--die-with-parent",
        "--setenv", "PATH", f"/venv/bin:{PYROOT}/bin:/usr/bin:/bin", "--setenv", "HOME", "/tmp", "--setenv", "PYTHONPATH", "/venv/lib/python3.12/site-packages",
        "/bin/sh", "-c", command,
    ]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout + p.stderr)[:MAX_OUT]
        return {"exit_code": p.returncode, "output": out}
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "output": f"timed out after {timeout}s"}
