"""Platform-neutral command lines for subprocess-provider tests."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys


def python_command(code: str) -> str:
    argv = [sys.executable, "-c", code]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def stdin_echo_command() -> str:
    return python_command("import sys;sys.stdout.write(sys.stdin.read())")
