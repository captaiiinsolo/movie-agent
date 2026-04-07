#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from movie_agent_lib import (
    build_client,
    choose_completed_target,
    db_older_than_days,
    find_video_file,
    format_bytes,
    load_config,
    normalize_movie_folder,
    run_ranked_search,
    safe_move,
    scan_path,
)


def print_candidates(query: str, total: int, ranked, choice: int) -> None:
    print(f"Query: {query}")
    print(f"Search results seen: {total}")
    print()
    for idx, candidate in enumerate(ranked, start=1):
        raw = candidate.raw
        name = raw.get("fileName") or raw.get("file_name") or raw.get("fileUrl") or raw.get("descrLink") or raw.get("name") or "(unknown)"
        size = int(raw.get("fileSize") or raw.get("file_size") or 0)
        seeders = raw.get("nbSeeders") or raw.get("nb_seeders") or raw.get("seeders") or 0
        leechers = raw.get("nbLeechers") or raw.get("nb_leechers") or raw.get("leechers") or 0
        prefix = "=>" if idx == choice else "  "
        print(f"{prefix} Option {idx}: {name}")
        print(f"{prefix}   Score: {candidate.score:.1f} | Size: {format_bytes(size)} | Seeders/Leechers: {seeders}/{leechers}")
        print(f"{prefix}   Why: {', '.join(candidate.reasons[:6])}")
        print()


def monitor_for_completion(client, downloads: Path, name_hint: str | None, timeout_seconds: int, poll_seconds: int) -> Path:
    deadline = time.time() + timeout_seconds
    last_state = None

    while time.time() < deadline:
        torrents = client.list_torrents("all")
        candidates = []
        for torrent in torrents:
            name = (torrent.get("name") or "")
            if name_hint and name_hint.lower() not in name.lower():
                continue
            candidates.append(torrent)

        candidates.sort(key=lambda t: t.get("added_on", 0), reverse=True)
        if candidates:
            torrent = candidates[0]
            state = torrent.get("state")
            progress = float(torrent.get("progress", 0))
            if state != last_state:
                print(f"Torrent state: {state}, progress={progress:.2%}")
                last_state = state
            if progress >= 1.0 or state in {"uploading", "stalledUP", "queuedUP", "forcedUP"}:
                return choose_completed_target(downloads, name_hint=name_hint)

        time.sleep(poll_seconds)

    raise RuntimeError("Timed out waiting for torrent completion")


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end movie agent orchestrator")
    parser.add_argument("query", help="Movie query, e.g. 'Beethoven 1992'")
    parser.add_argument("--choice", type=int, default=1, help="Ranked option to use")
    parser.add_argument("--limit", type=int, default=5, help="Number of ranked results to consider")
    parser.add_argument("--approve-download", action="store_true", help="Actually submit the chosen release to qBittorrent")
    parser.add_argument("--wait", action="store_true", help="Wait for qBittorrent completion after submission")
    parser.add_argument("--approve-move", action="store_true", help="Actually move to Movies after scan and normalization")
    parser.add_argument("--allow-stale-db", action="store_true", help="Proceed even if ClamAV DB appears stale")
    parser.add_argument("--completed-path", help="Explicit completed download path, bypass qBittorrent waiting")
    parser.add_argument("--timeout", type=int, default=7200, help="Wait timeout in seconds when monitoring completion")
    parser.add_argument("--poll", type=int, default=10, help="Poll interval in seconds when monitoring completion")
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

    print_candidates(args.query, payload.get("total", 0), ranked, args.choice)
    selected = ranked[args.choice - 1]
    raw = selected.raw
    target = raw.get("fileUrl") or raw.get("descrLink")
    selected_name = raw.get("fileName") or raw.get("name") or raw.get("descrLink") or "selected release"

    if not args.approve_download:
        print("Download approval not provided.")
        print("Preview complete. Re-run with --approve-download to submit to qBittorrent.")
        return 0

    if not target:
        print("Selected result does not expose a usable download or magnet URL.")
        return 1

    response = client.add_torrent_url(target, savepath=config["paths"]["downloads"])
    print("Submission response:", response or "<empty>")
    print(f"Submitted: {selected_name}")

    completed_path = Path(args.completed_path).expanduser() if args.completed_path else None
    if completed_path is None:
        if not args.wait:
            print("Submission complete. Re-run later with --wait or provide --completed-path for postprocess.")
            return 0
        completed_path = monitor_for_completion(
            client,
            Path(config["paths"]["downloads"]),
            name_hint=args.query,
            timeout_seconds=args.timeout,
            poll_seconds=args.poll,
        )

    print(f"Completed target: {completed_path}")

    clean, stale_by_scan, scan_log = scan_path(completed_path)
    stale = stale_by_scan or db_older_than_days(7)
    print(f"Scan clean: {clean}")
    print(f"DB stale signal: {stale}")

    if not clean:
        print(scan_log)
        return 1
    if stale and not args.allow_stale_db:
        print(scan_log)
        print("ClamAV database appears stale. Approval-gated sudo freshclam is required before continuing.")
        return 2

    normalized_root, actions = normalize_movie_folder(
        completed_path,
        keep_nfo=config["postprocess"]["keep_nfo"],
        remove_junk_txt=config["postprocess"]["remove_junk_txt"],
    )
    for action in actions:
        print(f"Postprocess: {action}")

    video = find_video_file(normalized_root)
    if video:
        print(f"Normalized video: {video}")

    if not args.approve_move:
        print("Move approval not provided.")
        print(f"Preview complete. Normalized path: {normalized_root}")
        return 0

    final_path, move_actions = safe_move(normalized_root, Path(config["paths"]["movies_destination"]))
    for action in move_actions:
        print(f"Move: {action}")
    print(f"Final path: {final_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
