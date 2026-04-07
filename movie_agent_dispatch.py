#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from movie_agent_lib import build_client, load_config

STATE_PATH = Path("/home/santos-family/.openclaw/workspace/movie-agent/state/live_state.json")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


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
        active_hash = state.get("active_torrent_hash")
        if active_hash:
            try:
                cfg = load_config()
                client = build_client(cfg)
                client.login()
                client.pause_torrents([active_hash])
                client.delete_torrents([active_hash], delete_files=False)
                print(f"Canceled tracked torrent: {active_hash}")
            except Exception as exc:
                print(f"Warning: could not cancel tracked torrent cleanly: {exc}")
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
        options = state.get("options") or []
        idx = choice - 1
        selected = options[idx] if 0 <= idx < len(options) else {}
        target = selected.get("fileUrl") or selected.get("downloadUrl") or selected.get("magnetUri") or ""
        match = re.search(r"btih:([A-Fa-f0-9]+)", target)
        if match:
            state["active_torrent_hash"] = match.group(1).lower()
            save_state(state)
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
