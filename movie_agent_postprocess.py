#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from movie_agent_lib import (
    choose_completed_target,
    db_older_than_days,
    freshclam_approval_command,
    load_config,
    normalize_movie_folder,
    run_freshclam_with_sudo,
    safe_move,
    scan_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor/scan/postprocess a completed movie download.")
    parser.add_argument("path_positional", nargs="?", help="Explicit completed download path to process")
    parser.add_argument("--path", help="Explicit completed download path to process")
    parser.add_argument("--name-hint", help="Name hint to find in downloads folder")
    parser.add_argument("--allow-stale-db", action="store_true", help="Proceed with scan result even if database appears stale")
    parser.add_argument("--update-definitions", action="store_true", help="Attempt sudo freshclam before rescanning when DB is stale")
    parser.add_argument("--move", action="store_true", help="Actually move to Movies destination after normalization and scan")
    args = parser.parse_args()

    config = load_config()
    downloads = Path(config["paths"]["downloads"])
    movies_destination = Path(config["paths"]["movies_destination"])

    selected_path = args.path or args.path_positional
    target = Path(selected_path).expanduser() if selected_path else choose_completed_target(downloads, args.name_hint)
    if not target.exists():
        raise RuntimeError(f"Target does not exist: {target}")

    print(f"Target: {target}")

    clean, stale_by_scan, scan_log = scan_path(target)
    stale = stale_by_scan or db_older_than_days(7)
    print(f"Scan clean: {clean}")
    print(f"DB stale signal: {stale}")

    if not clean:
        print(scan_log)
        raise RuntimeError("ClamAV scan did not pass cleanly")

    if stale and not args.allow_stale_db and not args.update_definitions:
        print(scan_log)
        print("ClamAV database appears stale.")
        print(f"Approval required to continue: {freshclam_approval_command()}")
        raise RuntimeError("Stale ClamAV database, update required or explicitly override")

    if stale and args.update_definitions:
        code, stdout, stderr = run_freshclam_with_sudo()
        print(stdout)
        if code != 0:
            print(stderr)
            raise RuntimeError("freshclam update failed")

        clean, stale_by_scan, scan_log = scan_path(target)
        stale = stale_by_scan or db_older_than_days(7)
        print(f"Rescan clean: {clean}")
        print(f"DB stale signal after update: {stale}")
        if not clean:
            print(scan_log)
            raise RuntimeError("ClamAV rescan did not pass cleanly")
        if stale and not args.allow_stale_db:
            print(scan_log)
            raise RuntimeError("ClamAV database still appears stale after update")

    normalized_root, actions = normalize_movie_folder(
        target,
        keep_nfo=config["postprocess"]["keep_nfo"],
        remove_junk_txt=config["postprocess"]["remove_junk_txt"],
    )
    for action in actions:
        print(f"Postprocess: {action}")

    if not args.move:
        print("Preview only. No move performed.")
        print(f"Normalized path: {normalized_root}")
        print("Summary: scan clean, normalized, awaiting move approval.")
        return 0

    try:
        final_path, move_actions = safe_move(normalized_root, movies_destination)
    except PermissionError as exc:
        print(str(exc))
        print("Summary: scan/normalize succeeded, move blocked pending elevated approval.")
        return 4
    for action in move_actions:
        print(f"Move: {action}")
    print(f"Final path: {final_path}")
    print("Summary: scan clean, normalized, and moved successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
