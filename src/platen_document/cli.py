"""Command-line diagnostics for the standalone SDK."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from .api import EngineConfiguration
from .diagnostics import build_doctor_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="platen-document")
    parser.add_argument("command", choices=("doctor",))
    args = parser.parse_args(argv)
    if args.command == "doctor":
        print(json.dumps(build_doctor_report(EngineConfiguration.from_env()), indent=2, sort_keys=True))
    return 0
