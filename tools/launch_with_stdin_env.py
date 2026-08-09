"""Launch a protected background process with secrets supplied only over stdin.

The JSON envelope is consumed in memory. Environment values are never written
to disk and never appear in the child command line.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _set_windows_console_echo(enabled: bool):
    """Toggle terminal echo while reading an in-memory secret envelope."""
    if os.name != "nt" or not sys.stdin.isatty():
        return None
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-10)
    mode = ctypes.c_uint()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return None
    original = int(mode.value)
    echo_input = 0x0004
    updated = original | echo_input if enabled else original & ~echo_input
    kernel32.SetConsoleMode(handle, updated)
    return handle, original


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pipe",
        help="Optional Windows named pipe carrying the in-memory JSON envelope",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Keep the launcher alive and return the child process exit code",
    )
    args = parser.parse_args()
    if args.pipe:
        with open(args.pipe, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
    else:
        console_state = _set_windows_console_echo(False)
        try:
            payload = json.load(sys.stdin)
        finally:
            if console_state is not None:
                handle, original_mode = console_state
                import ctypes

                ctypes.windll.kernel32.SetConsoleMode(handle, original_mode)
    command = [str(value) for value in payload["command"]]
    cwd = Path(payload["cwd"]).resolve()
    log_path = Path(payload["log_path"]).resolve()
    pid_path = Path(payload["pid_path"]).resolve()
    environment = os.environ.copy()
    environment.update(
        {str(key): str(value) for key, value in payload["environment"].items()}
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    creation_flags = 0
    if os.name == "nt":
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
    temporary = pid_path.with_suffix(pid_path.suffix + ".tmp")
    temporary.write_text(str(process.pid) + "\n", encoding="utf-8")
    temporary.replace(pid_path)
    print(json.dumps({"launched": True, "pid": process.pid}))
    sys.stdout.flush()
    if args.wait:
        return process.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
