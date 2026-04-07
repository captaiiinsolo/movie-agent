#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from movie_agent_lib import build_client, is_addable_target, load_config
from movie_agent_live import STATE_PATH, load_state, save_state

YES_WORDS = {"yes", "y", "download", "download it", "go ahead", "do it", "approve"}
CLEAR_WORDS = {"clear", "cancel", "stop", "nevermind", "never mind"}


def dispatch_message(message: str, approve_download: bool = False) -> int:
    text = (message or "").strip()
    lowered = text.lower()
    state = load_state()

    if not text:
        print("Send a movie title, a result number, or 'yes' to confirm the pinned choice.")
        return 1

    if lowered in CLEAR_WORDS:
        save_state({})
        print("Cleared live movie-agent state.")
        return 0

    if text.isdigit():
        options = state.get("options") or []
        choice = int(text)
        idx = choice - 1
        if not options:
            print("No active search state. Send a movie title first.")
            return 1
        if idx < 0 or idx >= len(options):
            print(f"Choice out of range. Available: 1-{len(options)}")
            return 1
        selected = options[idx]
        ranked_options = state.get("ranked_options") or []
        selected_ranked = ranked_options[idx] if idx < len(ranked_options) else None
        state["selected_choice"] = choice
        state["selected_name"] = selected.get("fileName") or selected.get("name")
        state["selected_target"] = selected.get("fileUrl") or selected.get("downloadUrl") or selected.get("magnetUri") or ""
        if selected_ranked is not None:
            state["selected_score"] = selected_ranked.get("score")
            state["selected_reasons"] = selected_ranked.get("reasons")
        save_state(state)
        print(f"Selected option {choice}: {state['selected_name']}")
        print("Selection is now pinned to this exact result.")
        print("Reply yes to download, or send another movie title.")
        return 0

    if lowered in YES_WORDS:
        target = state.get("selected_target") or ""
        name = state.get("selected_name") or "selected release"
        choice = state.get("selected_choice")
        query = state.get("query") or ""

        if not target:
            print("No pinned selection found. Send a movie title first, then pick a number.")
            return 1

        print(f"Pinned selection from live state: option {choice} for query '{query}'")
        print(f"Selected: {name}")

        if not is_addable_target(target):
            print("Pinned selection is not directly addable.")
            return 1

        if not approve_download:
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

    config = load_config()
    client = build_client(config)
    client.login()
    from movie_agent_lib import format_bytes, run_ranked_search

    payload, ranked = run_ranked_search(client, config, text, limit=100, plugins="piratebay,one337x,kickasstorrents,torrentgalaxy")
    addable = [
        c for c in ranked
        if is_addable_target(c.raw.get("fileUrl") or c.raw.get("downloadUrl") or c.raw.get("magnetUri") or "")
    ]
    rejected = [
        c for c in ranked
        if not is_addable_target(c.raw.get("fileUrl") or c.raw.get("downloadUrl") or c.raw.get("magnetUri") or "")
    ]
    addable = sorted(
        addable,
        key=lambda c: (
            c.score,
            int(c.raw.get("nbSeeders") or c.raw.get("nb_seeders") or c.raw.get("seeders") or 0),
        ),
        reverse=True,
    )
    rejected = sorted(
        rejected,
        key=lambda c: (
            int(c.raw.get("nbSeeders") or c.raw.get("nb_seeders") or c.raw.get("seeders") or 0),
            c.score,
        ),
        reverse=True,
    )
    using_addable = bool(addable)
    ranked = addable if addable else rejected
    limit = 5
    limited = ranked[:limit]
    state = {
        "query": text,
        "results_seen": payload.get("total", 0),
        "options": [candidate.raw for candidate in limited],
        "ranked_options": [
            {
                "rank": idx,
                "name": candidate.raw.get("fileName") or candidate.raw.get("name"),
                "score": candidate.score,
                "reasons": candidate.reasons,
                "target": candidate.raw.get("fileUrl") or candidate.raw.get("downloadUrl") or candidate.raw.get("magnetUri") or "",
                "raw": candidate.raw,
            }
            for idx, candidate in enumerate(limited, start=1)
        ],
        "addable_results_found": len(addable),
    }
    save_state(state)

    lines = [f"Results for: {text}"]
    lines.append("Reply with a number to choose one." if using_addable else "No directly addable results were found in the current search set.")
    lines.append("")
    for idx, candidate in enumerate(limited, start=1):
        raw = candidate.raw
        seeders = raw.get("nbSeeders") or raw.get("nb_seeders") or raw.get("seeders") or 0
        size = int(raw.get("fileSize") or raw.get("file_size") or 0)
        addable_text = "addable" if is_addable_target(raw.get("fileUrl") or raw.get("downloadUrl") or raw.get("magnetUri") or "") else "not-addable"
        lines.append(f"{idx}. {raw.get('fileName') or raw.get('name')}")
        lines.append(f"   size: {format_bytes(size)} | seeds: {seeders} | score: {candidate.score:.1f} | {addable_text}")
        lines.append(f"   why: {', '.join(candidate.reasons[:4])}")
        lines.append("")
    print("\n".join(lines).strip())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch Telegram/OpenClaw movie-agent messages through pinned live state.")
    parser.add_argument("message", nargs="?", default="", help="Incoming user chat message")
    parser.add_argument("--approve-download", action="store_true", help="Actually submit the pinned selection")
    args = parser.parse_args()
    return dispatch_message(args.message, approve_download=args.approve_download)


if __name__ == "__main__":
    raise SystemExit(main())
