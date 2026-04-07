#!/usr/bin/env python3
from __future__ import annotations

import argparse

from movie_agent_lib import build_client, is_addable_target, load_config, run_ranked_search, summarize_candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Search and rank movie releases from qBittorrent search.")
    parser.add_argument("query", help="Movie query, e.g. 'Beethoven 1992'")
    parser.add_argument("--limit", type=int, default=5, help="How many ranked results to show")
    parser.add_argument("--sort", choices=["score", "seeders"], default="score", help="Display results sorted by score or seeders")
    args = parser.parse_args()

    config = load_config()
    client = build_client(config)
    client.login()
    payload, ranked = run_ranked_search(client, config, args.query, limit=max(args.limit, 100))

    if args.sort == "seeders":
        ranked = sorted(
            ranked,
            key=lambda c: (
                1 if is_addable_target(c.raw.get("fileUrl") or c.raw.get("downloadUrl") or c.raw.get("magnetUri") or "") else 0,
                int(c.raw.get("nbSeeders") or c.raw.get("nb_seeders") or c.raw.get("seeders") or 0),
                c.score,
            ),
            reverse=True,
        )
    ranked = ranked[: args.limit]

    print(f"Query: {args.query}")
    print(f"Search results seen: {payload.get('total', 0)}")
    print(f"Display sort: {args.sort}")
    print()

    for idx, candidate in enumerate(ranked, start=1):
        raw = candidate.raw
        descr = raw.get("descrLink") or ""
        print(f"Option {idx}")
        print(summarize_candidate(candidate))
        if descr:
            print(f"  Source: {descr}")
        print()

    if not ranked:
        print("No usable results found.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
