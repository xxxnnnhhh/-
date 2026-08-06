# -*- coding: utf-8 -*-
"""Detached launcher for the story machine (avoids PowerShell 5.1 encoding issues)."""
import os
import signal
import subprocess
import sys
import time


ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")


def kill_stale():
    import ctypes

    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run.py*' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass


def main():
    kill_stale()
    time.sleep(1)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    stdout = open(os.path.join(ROOT, "logs", "story_machine_stdout.log"), "a", encoding="utf-8")
    stderr = open(os.path.join(ROOT, "logs", "story_machine_stderr.log"), "a", encoding="utf-8")
    proc = subprocess.Popen(
        [PYTHON, "run.py"],
        cwd=ROOT,
        env=env,
        stdout=stdout,
        stderr=stderr,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    with open(os.path.join(ROOT, "story_machine.pid"), "w") as f:
        f.write(str(proc.pid))
    print(f"Started story machine PID {proc.pid}")


if __name__ == "__main__":
    main()
