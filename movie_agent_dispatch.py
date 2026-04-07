#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from movie_agent_lib import build_client, is_addable_target, load_config

STATE_PATH = Path("/home/santos-family/.openclaw/workspace/movie-agent/state/live_state.json")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch the exact movie selected in live state to qBittorrent.")
    parser.add_argument("--approve-download", action="store_true", help="Actually submit the pinned selection")
    args = parser.parse_args()

    state = load_state()
    target = state.get("selected_target") or ""
    name = state.get("selected_name") or "selected release"
    choice = state.get("selected_choice")
    query = state.get("query") or ""

    if not target:
        print("No pinned selection found. Run live search and choose an option first.")
        return 1

    print(f"Pinned selection from live state: option {choice} for query '{query}'")
    print(f"Selected: {name}")

    if not is_addable_target(target):
        print("Pinned selection is not directly addable.")
        return 1

    if not args.approve_download:
        print("Download approval not provided.")
        print("Re-run with --approve-download to submit this exact pinned result.")
        return 0

    config = load_config()
    client = build_client(config)
    client.login()
    response = client.add_torrent_url(target, savepath=config["paths"]["downloads"])
    print("Submission response:", response or "<empty>")
    print(f"Submitted exact pinned selection: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
