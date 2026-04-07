#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

from movie_agent_monitor import track_torrent

from movie_agent_lib import (
    build_client,
    choose_completed_target,
    db_older_than_days,
    find_video_file,
    format_bytes,
    freshclam_approval_command,
    is_addable_target,
    load_config,
    normalize_movie_folder,
    run_freshclam_with_sudo,
    run_ranked_search,
    safe_move,
    scan_path,
    summarize_candidate,
)


def print_candidates(query: str, total: int, ranked, choice: int, display_sort: str) -> None:
    print(f"Query: {query}")
    print(f"Search results seen: {total}")
    print(f"Display sort: {display_sort}")
    print()
    for idx, candidate in enumerate(ranked, start=1):
        prefix = "=>" if idx == choice else "  "
        summary = summarize_candidate(candidate).replace("\n", f"\n{prefix}   ")
        first, rest = summary.split("\n", 1)
        print(f"{prefix} Option {idx}: {first.replace('Name: ', '')}")
        print(f"{prefix}   {rest}")
        print()


def select_fallback_torrent(current_torrents, before_snapshot, name_hint: str | None, debug: bool = False):
    lowered_hint = (name_hint or "").lower()
    hint_tokens = [token for token in lowered_hint.replace('.', ' ').replace('-', ' ').replace('_', ' ').split() if token]
    scored = []

    for item in current_torrents:
        item_hash = item.get("hash")
        name = (item.get("name") or "")
        lowered_name = name.lower()
        token_matches = sum(1 for token in hint_tokens if token in lowered_name)

        before = before_snapshot.get(item_hash, {})
        added_on = int(item.get("added_on") or 0)
        progress = float(item.get("progress") or 0)
        before_progress = float(before.get("progress") or 0)
        progress_delta = progress - before_progress
        added_delta = added_on - int(before.get("added_on") or 0)

        score = 0
        score += token_matches * 20
        score += 15 if added_delta > 0 else 0
        score += 20 if progress_delta > 0 else 0
        score += 10 if progress > 0 else 0
        score += min(10, max(0, int(progress * 10)))
        score += min(10, max(0, int((time.time() - added_on) * -1 / 60))) if added_on else 0
        scored.append((score, item))

    scored.sort(key=lambda pair: (pair[0], pair[1].get("added_on", 0)), reverse=True)
    if debug:
        print("Fallback candidates:")
        for score, item in scored[:8]:
            item_hash = item.get("hash")
            before = before_snapshot.get(item_hash, {})
            print(
                f"  score={score} | name={item.get('name')} | state={item.get('state')} | "
                f"progress={float(item.get('progress') or 0):.2%} | "
                f"added_on={item.get('added_on')} | before_added_on={before.get('added_on')} | "
                f"before_progress={float(before.get('progress') or 0):.2%}"
            )
    return scored[0][1] if scored else None


def send_telegram_message(target: str | None, message: str) -> None:
    if not target:
        return
    subprocess.run(
        [
            "openclaw", "message", "send",
            "--channel", "telegram",
            "--target", target,
            "--message", message,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def maybe_send_progress_update(target: str | None, query: str, percent: int, torrent: dict) -> None:
    return


def maybe_send_scan_update(target: str | None, completed_path: Path, clean: bool, stale: bool) -> None:
    if not target:
        return
    status = "clean" if clean else "failed"
    suffix = " (definitions stale)" if stale else ""
    message = f"ClamAV scan {status} for {completed_path.name}{suffix}"
    subprocess.run(
        [
            "openclaw", "message", "send",
            "--channel", "telegram",
            "--target", target,
            "--message", message,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def monitor_for_completion(client, downloads: Path, torrent_hash: str | None, name_hint: str | None, timeout_seconds: int, poll_seconds: int, before_snapshot: dict[str, dict], notify_target: str | None = None, notify_query: str | None = None) -> tuple[Path | None, dict | None]:
    deadline = time.time() + timeout_seconds
    last_state = None
    last_progress = None
    tracked_torrent = None
    sent_milestones: set[int] = set()

    while time.time() < deadline:
        torrents = client.list_torrents("all")
        torrent = None

        if torrent_hash:
            for item in torrents:
                if item.get("hash") == torrent_hash:
                    torrent = item
                    break

        if torrent is None:
            torrent = select_fallback_torrent(torrents, before_snapshot, name_hint, debug=(last_state is None))

        if torrent is not None:
            tracked_torrent = torrent
            state = torrent.get("state")
            progress = float(torrent.get("progress", 0))
            if state != last_state or progress != last_progress:
                print(f"Torrent state: {state}, progress={progress:.2%}, name={torrent.get('name')}")
                last_state = state
                last_progress = progress
            for milestone in (25, 50, 75):
                if progress >= milestone / 100 and milestone not in sent_milestones:
                    maybe_send_progress_update(notify_target, notify_query or name_hint or "download", milestone, torrent)
                    sent_milestones.add(milestone)
            if progress >= 1.0 or state in {"uploading", "stalledUP", "queuedUP", "forcedUP"}:
                maybe_send_progress_update(notify_target, notify_query or name_hint or "download", 100, torrent)
                content_path = torrent.get("content_path") or torrent.get("save_path") or ""
                if content_path:
                    return Path(content_path), torrent
                return choose_completed_target(downloads, name_hint=name_hint), torrent

        time.sleep(poll_seconds)

    return None, tracked_torrent


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end movie agent orchestrator")
    parser.add_argument("query", help="Movie query, e.g. 'Beethoven 1992'")
    parser.add_argument("--choice", type=int, default=1, help="Displayed option to use")
    parser.add_argument("--limit", type=int, default=5, help="Number of results to display")
    parser.add_argument("--sort", choices=["score", "seeders"], default="score", help="Display results sorted by score or seeders")
    parser.add_argument("--approve-download", action="store_true", help="Actually submit the chosen release to qBittorrent")
    parser.add_argument("--wait", action="store_true", help="Wait for qBittorrent completion after submission")
    parser.add_argument("--approve-move", action="store_true", help="Actually move to Movies after scan and normalization")
    parser.add_argument("--allow-stale-db", action="store_true", help="Proceed even if ClamAV DB appears stale")
    parser.add_argument("--update-definitions", action="store_true", help="Run sudo freshclam before rescanning when DB is stale")
    parser.add_argument("--completed-path", help="Explicit completed download path, bypass qBittorrent waiting")
    parser.add_argument("--timeout", type=int, default=7200, help="Wait timeout in seconds when monitoring completion")
    parser.add_argument("--poll", type=int, default=10, help="Poll interval in seconds when monitoring completion")
    parser.add_argument("--notify-target", help="Telegram target/chat id for progress notifications")
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
    if not ranked:
        print("No usable results found.")
        return 1
    if args.choice < 1 or args.choice > len(ranked):
        print(f"Choice {args.choice} is out of range. Available options: 1-{len(ranked)}")
        return 1

    print_candidates(args.query, payload.get("total", 0), ranked, args.choice, args.sort)
    selected = ranked[args.choice - 1]
    raw = selected.raw
    target = raw.get("fileUrl") or raw.get("downloadUrl") or raw.get("magnetUri") or raw.get("descrLink")
    selected_name = raw.get("fileName") or raw.get("name") or raw.get("descrLink") or "selected release"

    if not args.approve_download:
        print("Download approval not provided.")
        print("Preview complete. Re-run with --approve-download to submit to qBittorrent.")
        print("Summary: search complete, awaiting download approval.")
        return 0

    if not target or not is_addable_target(target):
        print("Selected result does not expose a directly addable magnet or .torrent URL.")
        print(f"Target seen: {target or '<none>'}")
        print("Summary: selected result is not safely addable.")
        return 1

    before_torrents = client.list_torrents("all")
    before_hashes = {item.get("hash") for item in before_torrents}
    before_snapshot = {item.get("hash"): item for item in before_torrents if item.get("hash")}
    response = client.add_torrent_url(target, savepath=config["paths"]["downloads"])
    print("Submission response:", response or "<empty>")
    print(f"Submitted: {selected_name}")
    # durable monitor owns user-facing milestone notifications
    duplicate_submission = (response or "").strip().lower() == "fails."
    if duplicate_submission:
        print("qBittorrent reported the torrent may already exist, continuing with tracker lookup.")

    torrent_hash = None
    for _ in range(10):
        time.sleep(1)
        current = client.list_torrents("all")
        new_items = [item for item in current if item.get("hash") not in before_hashes]
        if new_items:
            new_items.sort(key=lambda t: t.get("added_on", 0), reverse=True)
            tracked_item = new_items[0]
            torrent_hash = tracked_item.get("hash")
            print(f"Tracked torrent hash: {torrent_hash}")
            if torrent_hash and args.notify_target:
                track_torrent(
                    torrent_hash,
                    tracked_item.get("name") or selected_name,
                    args.notify_target,
                    tracked_item.get("content_path") or tracked_item.get("save_path") or "",
                )
            break

    if torrent_hash is None:
        print("No new torrent hash detected after submission, falling back to heuristic tracking.")
        current = client.list_torrents("all")
        print("Top torrents after submission:")
        top = sorted(current, key=lambda t: t.get('added_on', 0), reverse=True)[:8]
        for item in top:
            print(
                f"  name={item.get('name')} | state={item.get('state')} | "
                f"progress={float(item.get('progress') or 0):.2%} | added_on={item.get('added_on')}"
            )
        fallback_item = select_fallback_torrent(current, before_snapshot, selected_name)
        if fallback_item is not None and fallback_item.get('hash') and args.notify_target:
            track_torrent(
                fallback_item.get('hash'),
                fallback_item.get('name') or selected_name,
                args.notify_target,
                fallback_item.get('content_path') or fallback_item.get('save_path') or '',
            )

    completed_path = Path(args.completed_path).expanduser() if args.completed_path else None
    completed_torrent = None
    if completed_path is None:
        if not args.wait:
            if duplicate_submission:
                print("Submission was already present in qBittorrent. Re-run with --wait to attach to the existing torrent, or provide --completed-path for postprocess.")
            else:
                print("Submission complete. Re-run later with --wait or provide --completed-path for postprocess.")
            return 0
        visible_torrents = client.list_torrents("all")
        if not visible_torrents:
            print("Cannot use --wait on this setup right now: qBittorrent Web API torrent listing is returning zero torrents.")
            print("Search/add endpoints work, but /api/v2/torrents/info and /api/v2/sync/maindata are not exposing active torrents to the script.")
            print("Use --completed-path for postprocess, or fix qBittorrent's torrent-list API visibility before using --wait.")
            print("Summary: download submitted, but wait/monitoring unavailable on this setup.")
            return 4
        completed_path, completed_torrent = monitor_for_completion(
            client,
            Path(config["paths"]["downloads"]),
            torrent_hash=torrent_hash,
            name_hint=selected_name,
            timeout_seconds=args.timeout,
            poll_seconds=args.poll,
            before_snapshot=before_snapshot,
            notify_target=args.notify_target,
            notify_query=args.query,
        )
        if completed_path is None:
            if completed_torrent is not None:
                print(
                    "Wait timeout reached. "
                    f"Last seen: state={completed_torrent.get('state')}, "
                    f"progress={float(completed_torrent.get('progress') or 0):.2%}, "
                    f"name={completed_torrent.get('name')}"
                )
            else:
                print("Wait timeout reached before a matching torrent could be tracked.")
            print("Summary: download submitted and tracking works, but completion has not happened yet.")
            return 5

    print(f"Completed target: {completed_path}")

    if completed_torrent and completed_torrent.get("hash"):
        torrent_hash_value = completed_torrent.get("hash")
        print(f"Pausing completed torrent: {completed_torrent.get('name')}")
        client.pause_torrents([torrent_hash_value])
        print(f"Removing torrent from qBittorrent (keeping files): {completed_torrent.get('name')}")
        client.delete_torrents([torrent_hash_value], delete_files=False)

    clean, stale_by_scan, scan_log = scan_path(completed_path)
    stale = stale_by_scan or db_older_than_days(7)
    print(f"Scan clean: {clean}")
    print(f"DB stale signal: {stale}")
    maybe_send_scan_update(args.notify_target, completed_path, clean, stale)

    if not clean:
        print(scan_log)
        print("Summary: scan failed, no move performed.")
        return 1

    if stale and not args.allow_stale_db and not args.update_definitions:
        print(scan_log)
        print("ClamAV database appears stale.")
        print(f"Approval required to continue: {freshclam_approval_command()}")
        print("Summary: download completed and scanned, waiting on freshclam approval before postprocess/move.")
        return 2

    if stale and args.update_definitions:
        code, stdout, stderr = run_freshclam_with_sudo()
        print(stdout)
        if code != 0:
            print(stderr)
            return 3
        clean, stale_by_scan, scan_log = scan_path(completed_path)
        stale = stale_by_scan or db_older_than_days(7)
        print(f"Rescan clean: {clean}")
        print(f"DB stale signal after update: {stale}")
        if not clean:
            print(scan_log)
            return 1
        if stale and not args.allow_stale_db:
            print(scan_log)
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
        print("Summary: download completed, scanned, normalized, awaiting move approval.")
        return 0

    try:
        final_path, move_actions = safe_move(normalized_root, Path(config["paths"]["movies_destination"]))
    except PermissionError as exc:
        print(str(exc))
        print("Summary: download completed, scanned, normalized, move blocked pending elevated approval.")
        return 4
    for action in move_actions:
        print(f"Move: {action}")
    print(f"Final path: {final_path}")
    print(f"Source exists after move: {normalized_root.exists()}")
    print(f"Destination exists after move: {final_path.exists()}")
    print("Summary: download completed, scanned, normalized, and moved successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
