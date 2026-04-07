#!/usr/bin/env python3
from __future__ import annotations

import argparse

from movie_agent_lib import build_client, format_bytes, load_config, run_ranked_search


def main() -> int:
    parser = argparse.ArgumentParser(description="Search and rank movie releases from qBittorrent search.")
    parser.add_argument("query", help="Movie query, e.g. 'Beethoven 1992'")
    parser.add_argument("--limit", type=int, default=5, help="How many ranked results to show")
    args = parser.parse_args()

    config = load_config()
    client = build_client(config)
    client.login()
    payload, ranked = run_ranked_search(client, config, args.query, limit=args.limit)

    print(f"Query: {args.query}")
    print(f"Search results seen: {payload.get('total', 0)}")
    print()

    for idx, candidate in enumerate(ranked, start=1):
        raw = candidate.raw
        name = raw.get("fileName") or raw.get("file_name") or raw.get("fileUrl") or raw.get("descrLink") or raw.get("name") or "(unknown)"
        size = int(raw.get("fileSize") or raw.get("file_size") or 0)
        seeders = raw.get("nbSeeders") or raw.get("nb_seeders") or raw.get("seeders") or 0
        leechers = raw.get("nbLeechers") or raw.get("nb_leechers") or raw.get("leechers") or 0
        descr = raw.get("descrLink") or ""
        print(f"Option {idx}")
        print(f"  Name: {name}")
        print(f"  Score: {candidate.score:.1f}")
        print(f"  Size: {format_bytes(size)}")
        print(f"  Seeders/Leechers: {seeders}/{leechers}")
        if descr:
            print(f"  Source: {descr}")
        print(f"  Why: {', '.join(candidate.reasons[:6])}")
        print()

    if not ranked:
        print("No usable results found.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
