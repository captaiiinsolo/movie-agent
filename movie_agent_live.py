#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from movie_agent_lib import is_addable_target, load_config, run_ranked_search, build_client, summarize_candidate

STATE_PATH = Path("/home/santos-family/.openclaw/workspace/movie-agent/state/live_state.json")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def render_options(query: str, ranked: list, limit: int) -> str:
    lines = [f"Results for: {query}", "Reply with a number to choose one.", ""]
    for idx, candidate in enumerate(ranked[:limit], start=1):
        raw = candidate.raw
        seeders = raw.get("nbSeeders") or raw.get("nb_seeders") or raw.get("seeders") or 0
        addable = is_addable_target(raw.get("fileUrl") or raw.get("downloadUrl") or raw.get("magnetUri") or "")
        addable_text = "addable" if addable else "not-addable"
        lines.append(f"{idx}. {raw.get('fileName') or raw.get('name')}")
        lines.append(f"   seeds: {seeders} | score: {candidate.score:.1f} | {addable_text}")
        lines.append(f"   why: {', '.join(candidate.reasons[:4])}")
        lines.append("")
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live conversation helper for movie-agent Telegram/OpenClaw flow.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    search_p = sub.add_parser("search")
    search_p.add_argument("query")
    search_p.add_argument("--limit", type=int, default=5)

    choose_p = sub.add_parser("choose")
    choose_p.add_argument("choice", type=int)

    clear_p = sub.add_parser("clear")

    args = parser.parse_args()
    state = load_state()

    if args.cmd == "clear":
        save_state({})
        print("Cleared live movie-agent state.")
        return 0

    if args.cmd == "search":
        config = load_config()
        client = build_client(config)
        client.login()
        payload, ranked = run_ranked_search(client, config, args.query, limit=100)
        ranked = sorted(
            ranked,
            key=lambda c: (
                1 if is_addable_target(c.raw.get("fileUrl") or c.raw.get("downloadUrl") or c.raw.get("magnetUri") or "") else 0,
                int(c.raw.get("nbSeeders") or c.raw.get("nb_seeders") or c.raw.get("seeders") or 0),
                c.score,
            ),
            reverse=True,
        )
        state = {
            "query": args.query,
            "results_seen": payload.get("total", 0),
            "options": [candidate.raw for candidate in ranked[: args.limit]],
        }
        save_state(state)
        print(render_options(args.query, ranked, args.limit))
        return 0

    if args.cmd == "choose":
        options = state.get("options") or []
        if not options:
            print("No active search state. Start with a search first.")
            return 1
        idx = args.choice - 1
        if idx < 0 or idx >= len(options):
            print(f"Choice out of range. Available: 1-{len(options)}")
            return 1
        selected = options[idx]
        state["selected_choice"] = args.choice
        state["selected_name"] = selected.get("fileName") or selected.get("name")
        save_state(state)
        print(f"Selected option {args.choice}: {state['selected_name']}")
        print("Reply yes to download, or search again.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
