#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

STATE_PATH = Path("/home/santos-family/.openclaw/workspace/movie-agent/state/live_state.json")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def run_cmd(args: list[str]) -> int:
    return subprocess.call([sys.executable, *args])


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch chat-like movie-agent intents into the live movie workflow.")
    parser.add_argument("message", help="Incoming user text")
    args = parser.parse_args()

    text = args.message.strip()
    lowered = text.lower()
    state = load_state()

    if lowered in {"clear", "cancel", "reset"}:
        return run_cmd(["movie_agent_live.py", "clear"])

    if lowered in {"yes", "y", "download it", "do it", "go ahead"}:
        choice = state.get("selected_choice")
        query = state.get("query")
        if not choice or not query:
            print("Nothing is selected yet. Search for a movie first.")
            return 1
        if not state.get("addable_results_found"):
            print("Current search results did not include directly addable releases. I recommend searching a different title variant or improving the search backend before downloading from this set.")
            return 1
        return run_cmd([
            "movie_agent_pick.py",
            query,
            "--limit",
            str(max(10, len(state.get("options") or []))),
            "--choice",
            str(choice),
            "--download",
            "--wait",
        ])

    if lowered in {"no", "n"}:
        print("Okay, no download started. Search again or choose another option.")
        return 0

    if re.fullmatch(r"\d+", text):
        return run_cmd(["movie_agent_live.py", "choose", text])

    return run_cmd(["movie_agent_live.py", "search", text, "--limit", "10"])


if __name__ == "__main__":
    raise SystemExit(main())
