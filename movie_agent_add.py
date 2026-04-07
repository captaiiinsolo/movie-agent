#!/usr/bin/env python3
from __future__ import annotations

import argparse

from movie_agent_lib import build_client, format_bytes, load_config, run_ranked_search


def main() -> int:
    parser = argparse.ArgumentParser(description="Search, choose, and optionally add a movie release to qBittorrent.")
    parser.add_argument("query", help="Movie query, e.g. 'Beethoven 1992'")
    parser.add_argument("--choice", type=int, default=1, help="Ranked option number to target")
    parser.add_argument("--limit", type=int, default=5, help="How many ranked results to gather")
    parser.add_argument("--approve", action="store_true", help="Actually add the selected result to qBittorrent")
    args = parser.parse_args()

    config = load_config()
    client = build_client(config)
    client.login()
    payload, ranked = run_ranked_search(client, config, args.query, limit=args.limit)

    if not ranked:
        print("No usable results found.")
        return 1

    if args.choice < 1 or args.choice > len(ranked):
        print(f"Choice {args.choice} is out of range. Available options: 1-{len(ranked)}")
        return 1

    print(f"Query: {args.query}")
    print(f"Search results seen: {payload.get('total', 0)}")
    print()

    for idx, candidate in enumerate(ranked, start=1):
        raw = candidate.raw
        name = raw.get("fileName") or raw.get("file_name") or raw.get("fileUrl") or raw.get("descrLink") or raw.get("name") or "(unknown)"
        size = int(raw.get("fileSize") or raw.get("file_size") or 0)
        seeders = raw.get("nbSeeders") or raw.get("nb_seeders") or raw.get("seeders") or 0
        leechers = raw.get("nbLeechers") or raw.get("nb_leechers") or raw.get("leechers") or 0
        prefix = "=>" if idx == args.choice else "  "
        print(f"{prefix} Option {idx}: {name}")
        print(f"{prefix}   Score: {candidate.score:.1f} | Size: {format_bytes(size)} | Seeders/Leechers: {seeders}/{leechers}")
        print(f"{prefix}   Why: {', '.join(candidate.reasons[:6])}")
        print()

    selected = ranked[args.choice - 1]
    raw = selected.raw
    target = raw.get("fileUrl") or raw.get("descrLink") or raw.get("fileUrl")

    if not target:
        print("Selected result does not expose a usable download/magnet URL through the API output.")
        return 1

    if not args.approve:
        print("Preview only. No download started.")
        print("Re-run with --approve to submit the selected result to qBittorrent.")
        return 0

    response = client.add_torrent_url(target, savepath=config["paths"]["downloads"])
    print("Submission response:", response or "<empty>")
    print("Selected result was submitted to qBittorrent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
