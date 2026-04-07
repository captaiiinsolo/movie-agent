#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from movie_agent_lib import build_client, load_config

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v"}
JUNK_TEXT_FILENAMES = {
    "torrent downloaded from uindex.org .txt",
    "torrent downloaded from uindex.org.txt",
    "downloaded from uindex.org.txt",
}


def sanitize_name(name: str) -> str:
    cleaned = name
    for token in ["www.UIndex.org", "UIndex.org", "YTS.MX", "YIFY", "[YTS.MX]", "[YTS]", " - "]:
        cleaned = cleaned.replace(token, " ")
    cleaned = " ".join(cleaned.split())
    return cleaned.strip(" -._")


def find_video_file(root: Path) -> Path | None:
    if root.is_file() and root.suffix.lower() in VIDEO_EXTENSIONS:
        return root
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            return path
    return None


def infer_title_year(name: str) -> tuple[str, str | None]:
    import re

    match = re.search(r"(.+?)\b((?:19|20)\d{2})\b", name)
    if match:
        title = sanitize_name(match.group(1))
        year = match.group(2)
        return title, year
    return sanitize_name(name), None


def run_command(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def clam_db_is_stale(stderr: str, stdout: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    return "outdated" in text or "update now" in text or "is older than" in text


def scan_path(target: Path) -> tuple[bool, bool, str]:
    code, stdout, stderr = run_command(["clamscan", "-r", str(target)])
    stale = clam_db_is_stale(stderr, stdout)
    clean = code == 0
    return clean, stale, f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}".strip()


def latest_db_mtime() -> float | None:
    db_dir = Path("/var/lib/clamav")
    candidates = list(db_dir.glob("*.cvd")) + list(db_dir.glob("*.cld"))
    if not candidates:
        return None
    return max(path.stat().st_mtime for path in candidates)


def db_older_than_days(days: int) -> bool:
    mtime = latest_db_mtime()
    if mtime is None:
        return True
    return (time.time() - mtime) > days * 86400


def remove_junk_txt_files(root: Path) -> list[Path]:
    removed: list[Path] = []
    for path in root.rglob("*.txt"):
        if path.name.lower().strip() in JUNK_TEXT_FILENAMES:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def normalize_movie_folder(source: Path, keep_nfo: bool = True, remove_junk_txt: bool = True) -> tuple[Path, list[str]]:
    actions: list[str] = []
    work_root = source

    if remove_junk_txt:
        removed = remove_junk_txt_files(work_root)
        if removed:
            actions.append(f"removed {len(removed)} junk txt file(s)")

    video = find_video_file(work_root)
    if video is None:
        raise RuntimeError("No video file found in completed download")

    title, year = infer_title_year(video.stem if video.is_file() else work_root.name)
    folder_name = f"{title} ({year})" if year else title
    file_name = f"{title} ({year}){video.suffix.lower()}" if year else f"{title}{video.suffix.lower()}"

    normalized_root = work_root.parent / folder_name
    if work_root != normalized_root:
        work_root.rename(normalized_root)
        actions.append(f"renamed folder to {normalized_root.name}")
        work_root = normalized_root
        video = find_video_file(work_root)
        if video is None:
            raise RuntimeError("Video file missing after folder rename")

    desired_video = video.with_name(file_name)
    if video != desired_video:
        video.rename(desired_video)
        actions.append(f"renamed video to {desired_video.name}")

    if not keep_nfo:
        for nfo in work_root.rglob("*.nfo"):
            nfo.unlink(missing_ok=True)
            actions.append(f"removed nfo {nfo.name}")

    return work_root, actions


def verify_same_tree(src: Path, dst: Path) -> bool:
    src_files = sorted(str(p.relative_to(src)) for p in src.rglob("*") if p.is_file())
    dst_files = sorted(str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file())
    return src_files == dst_files


def safe_move(source: Path, destination_parent: Path) -> tuple[Path, list[str]]:
    actions: list[str] = []
    destination = destination_parent / source.name

    if destination.exists():
        raise RuntimeError(f"Destination already exists: {destination}")

    same_device = source.stat().st_dev == destination_parent.stat().st_dev
    if same_device:
        source.rename(destination)
        actions.append("moved on same filesystem")
        return destination, actions

    shutil.copytree(source, destination)
    actions.append("copied across filesystems")

    if not verify_same_tree(source, destination):
        raise RuntimeError("Destination verification failed after cross-filesystem copy")

    shutil.rmtree(source)
    actions.append("removed original after verification")
    return destination, actions


def choose_completed_target(downloads: Path, name_hint: str | None = None) -> Path:
    candidates = []
    for path in downloads.iterdir():
        if name_hint and name_hint.lower() not in path.name.lower():
            continue
        candidates.append(path)

    if not candidates:
        raise RuntimeError("No matching download target found")

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor/scan/postprocess a completed movie download.")
    parser.add_argument("--path", help="Explicit completed download path to process")
    parser.add_argument("--name-hint", help="Name hint to find in downloads folder")
    parser.add_argument("--allow-stale-db", action="store_true", help="Proceed with scan result even if database appears stale")
    parser.add_argument("--move", action="store_true", help="Actually move to Movies destination after normalization and scan")
    args = parser.parse_args()

    config = load_config()
    downloads = Path(config["paths"]["downloads"])
    movies_destination = Path(config["paths"]["movies_destination"])

    target = Path(args.path).expanduser() if args.path else choose_completed_target(downloads, args.name_hint)
    if not target.exists():
        raise RuntimeError(f"Target does not exist: {target}")

    print(f"Target: {target}")

    stale_by_age = db_older_than_days(7)
    clean, stale_by_scan, scan_log = scan_path(target)
    stale = stale_by_age or stale_by_scan

    print(f"Scan clean: {clean}")
    print(f"DB stale signal: {stale}")

    if not clean:
        print(scan_log)
        raise RuntimeError("ClamAV scan did not pass cleanly")

    if stale and not args.allow_stale_db:
        print(scan_log)
        raise RuntimeError("ClamAV database appears stale. Run sudo freshclam, then rescan.")

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
        return 0

    final_path, move_actions = safe_move(normalized_root, movies_destination)
    for action in move_actions:
        print(f"Move: {action}")
    print(f"Final path: {final_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
