#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Normal-use movie workflow: show addable, high-quality options for manual choice.")
    parser.add_argument("query", help="Movie query, e.g. 'Toy Story 1995'")
    parser.add_argument("--limit", type=int, default=10, help="How many options to show")
    parser.add_argument("--choice", type=int, help="Displayed option number to submit")
    parser.add_argument("--download", action="store_true", help="Submit the chosen option to qBittorrent")
    parser.add_argument("--wait", action="store_true", help="Wait for completion after submission")
    parser.add_argument("--move", action="store_true", help="Move into Movies after scan/normalize")
    args = parser.parse_args()

    cmd = [
        sys.executable,
        "movie_agent_run.py",
        args.query,
        "--limit",
        str(args.limit),
        "--sort",
        "score",
    ]

    if args.choice is not None:
        cmd.extend(["--choice", str(args.choice)])
    if args.download:
        cmd.append("--approve-download")
    if args.wait:
        cmd.append("--wait")
    if args.move:
        cmd.append("--approve-move")

    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
