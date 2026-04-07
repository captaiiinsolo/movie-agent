#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

import tomllib

PRIMARY_CONFIG_PATH = Path("/home/santos-family/.openclaw/workspace/movie-agent/movie-agent.config.toml")
FALLBACK_CONFIG_PATH = Path("/home/santos-family/.openclaw/workspace/movie-agent.config.toml")
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v"}
JUNK_TEXT_FILENAMES = {
    "torrent downloaded from uindex.org .txt",
    "torrent downloaded from uindex.org.txt",
    "downloaded from uindex.org.txt",
    "torrent downloaded from torrenting.com.txt",
    "downloaded from publichd.se.txt",
    "downloaded from publichd.txt",
}
JUNK_IMAGE_FILENAMES = {
    "www.yify-torrents.com.jpg",
    "www.yts.mx.jpg",
    "yts.mx.jpg",
}


@dataclass
class Candidate:
    raw: dict[str, Any]
    score: float
    reasons: list[str]


class QBittorrentClient:
    def __init__(self, host: str, port: int, username: str, password: str):
        self.base = f"http://{host}:{port}"
        self.username = username
        self.password = password
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def post(self, path: str, data: dict[str, Any]) -> str:
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(self.base + path, data=body, method="POST")
        with self.opener.open(req, timeout=20) as resp:
            return resp.read().decode(errors="replace")

    def get_json(self, path: str) -> Any:
        req = urllib.request.Request(self.base + path, method="GET")
        with self.opener.open(req, timeout=20) as resp:
            return json.loads(resp.read().decode(errors="replace"))

    def login(self) -> None:
        result = self.post("/api/v2/auth/login", {"username": self.username, "password": self.password}).strip()
        if result != "Ok.":
            raise RuntimeError(f"qBittorrent login failed: {result}")

    def start_search(self, pattern: str, category: str = "all", plugins: str = "enabled") -> int:
        payload = json.loads(self.post("/api/v2/search/start", {
            "pattern": pattern,
            "category": category,
            "plugins": plugins,
        }))
        return int(payload["id"])

    def get_search_results(self, search_id: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return self.get_json(f"/api/v2/search/results?id={search_id}&limit={limit}&offset={offset}")

    def delete_search(self, search_id: int) -> None:
        self.post("/api/v2/search/delete", {"id": search_id})

    def add_torrent_url(self, url: str, savepath: str | None = None) -> str:
        payload: dict[str, Any] = {"urls": url}
        if savepath:
            payload["savepath"] = savepath
        return self.post("/api/v2/torrents/add", payload).strip()

    def list_torrents(self, filter_expr: str = "all") -> list[dict[str, Any]]:
        return self.get_json(f"/api/v2/torrents/info?filter={filter_expr}")

    def pause_torrents(self, hashes: list[str]) -> str:
        return self.post("/api/v2/torrents/pause", {"hashes": "|".join(hashes)}).strip()

    def delete_torrents(self, hashes: list[str], delete_files: bool = False) -> str:
        return self.post("/api/v2/torrents/delete", {"hashes": "|".join(hashes), "deleteFiles": "true" if delete_files else "false"}).strip()


def load_config() -> dict[str, Any]:
    config_path = PRIMARY_CONFIG_PATH if PRIMARY_CONFIG_PATH.exists() else FALLBACK_CONFIG_PATH
    return tomllib.loads(config_path.read_text())


def build_client(config: dict[str, Any]) -> QBittorrentClient:
    qb = config["qbittorrent"]
    return QBittorrentClient(qb["host"], int(qb["port"]), qb["username"], qb["password"])


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def parse_request(query: str) -> tuple[str, int | None]:
    match = re.search(r"\b(19|20)\d{2}\b", query)
    year = int(match.group(0)) if match else None
    title = query.replace(str(year), "").strip() if year else query.strip()
    return title, year


def title_year_match_score(name: str, title: str, year: int | None) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    normalized_name = normalize(name)
    normalized_title = normalize(title)

    if normalized_title and normalized_title in normalized_name:
        score += 40
        reasons.append("title match")
    else:
        score -= 50
        reasons.append("weak title match")

    if year is not None:
        if str(year) in name:
            score += 20
            reasons.append("year match")
        else:
            score -= 15
            reasons.append("year missing")

    return score, reasons


def is_addable_target(url: str) -> bool:
    lowered = (url or "").lower().strip()
    return lowered.startswith("magnet:?") or lowered.endswith(".torrent")


def summarize_candidate(candidate: Candidate) -> str:
    raw = candidate.raw
    name = raw.get("fileName") or raw.get("file_name") or raw.get("fileUrl") or raw.get("descrLink") or raw.get("name") or "(unknown)"
    size = int(raw.get("fileSize") or raw.get("file_size") or 0)
    seeders = raw.get("nbSeeders") or raw.get("nb_seeders") or raw.get("seeders") or 0
    leechers = raw.get("nbLeechers") or raw.get("nb_leechers") or raw.get("leechers") or 0
    addable = is_addable_target(raw.get("fileUrl") or raw.get("downloadUrl") or raw.get("magnetUri") or "")
    addable_text = "yes" if addable else "no"
    return (
        f"Name: {name}\n"
        f"  Score: {candidate.score:.1f} | Size: {format_bytes(size)} | Seeders/Leechers: {seeders}/{leechers} | Addable: {addable_text}\n"
        f"  Why: {', '.join(candidate.reasons[:6])}"
    )


def score_candidate(result: dict[str, Any], config: dict[str, Any], title: str, year: int | None) -> Candidate:
    prefs = config["preferences"]
    filters = config["filters"]["reject"]
    name = result.get("fileName") or result.get("file_name") or result.get("descrLink") or result.get("fileUrl") or result.get("file") or result.get("name") or ""
    site_url = result.get("descrLink") or ""
    lower = name.lower()
    score = 0.0
    reasons: list[str] = []

    match_score, match_reasons = title_year_match_score(name, title, year)
    score += match_score
    reasons.extend(match_reasons)

    source_quality_bonus = 0
    if "bluray" in lower or "blu-ray" in lower or "bdrip" in lower or "remux" in lower:
        source_quality_bonus = 24
        reasons.append("high-quality source")
    elif "web-dl" in lower or "webrip" in lower or "web rip" in lower:
        source_quality_bonus = 10
        reasons.append("web source")
    elif "hdtv" in lower:
        source_quality_bonus = 4
        reasons.append("hdtv source")
    score += source_quality_bonus

    group_hits = [group for group in prefs.get("preferred_groups", []) if group.lower() in lower]
    if group_hits:
        score += 10
        reasons.append(f"preferred group: {', '.join(group_hits)}")

    if "1080p" in lower:
        score += 20
        reasons.append("1080p preferred")
    elif "720p" in lower and prefs.get("allow_720p_fallback"):
        score += 8
        reasons.append("720p fallback")
    elif "2160p" in lower or "4k" in lower:
        if prefs.get("allow_4k_only_with_explicit_approval"):
            score -= 20
            reasons.append("4K requires explicit approval")

    if "x264" in lower or "h.264" in lower:
        score += 12
        reasons.append("x264 preferred")
    elif any(tag in lower for tag in ["x265", "h265", "hevc"]):
        if prefs.get("allow_x265"):
            score += 6
            reasons.append("x265 acceptable")
    if "av1" in lower:
        score -= 100
        reasons.append("AV1 rejected")

    if any(bad in lower for bad in ["cam", "telesync", " ts ", "screener"]):
        score -= 120
        reasons.append("rejected quality class")

    foreign_audio_tags = [
        "dual audio", "multi audio", "multi-audio", "3audio", "2audio", "ita", "italian", "latino", "espanol", "spanish", "french", "german", "russian", "hindi", "multi",
    ]
    if prefs.get("avoid_dual_audio") and any(tag in lower for tag in ["dual audio", "multi audio", "multi-audio", "3audio", "2audio"]):
        score -= 25
        reasons.append("dual-audio penalty")

    if prefs.get("avoid_foreign_dub_unless_requested") and any(tag in lower for tag in foreign_audio_tags):
        score -= 45
        reasons.append("foreign-audio penalty")

    if prefs.get("subtitles") == "english_only" and any(tag in lower for tag in ["eng", "english sub", "subs"]):
        score += 5
        reasons.append("english subs signal")

    size_bytes = int(result.get("fileSize") or result.get("file_size") or 0)
    size_gb = size_bytes / (1024 ** 3) if size_bytes else 0
    if size_gb:
        if size_gb > 12:
            score -= 20
            reasons.append("large encode penalty")
        elif 1.2 <= size_gb <= 5.5:
            score += 8
            reasons.append("efficient size")

    seeders = int(result.get("nbSeeders") or result.get("nb_seeders") or result.get("seeders") or 0)
    leechers = int(result.get("nbLeechers") or result.get("nb_leechers") or result.get("leechers") or 0)
    if seeders >= 10:
        score += 10
        reasons.append("healthy seed count")
    elif seeders <= 1:
        score -= 25
        reasons.append("very low seed count")
    if leechers > seeders * 3 and leechers > 10:
        score -= 10
        reasons.append("poor seed/leech ratio")

    reject_tokens = {
        "cam": [" cam ", ".cam.", "-cam", "camrip"],
        "ts": [" telesync ", " hdts ", ".ts.", "-ts-"],
        "telesync": ["telesync", "tele sync"],
        "screener": ["screener", "dvdscr"],
        "passworded_archive": ["password", ".rar", ".zip"],
        "tracker_spam": ["www.", "torrentgalaxy.to", "ettv", "torrent downloaded from"],
        "ambiguous_match": [],
    }
    matched_reject = False
    for reject in filters:
        patterns = reject_tokens.get(reject, [])
        if any(pattern in lower for pattern in patterns):
            matched_reject = True
            break
    if matched_reject:
        score -= 80
        reasons.append("matched reject filter")

    target_url = result.get("fileUrl") or result.get("downloadUrl") or result.get("magnetUri") or ""
    if is_addable_target(target_url):
        score += 12
        reasons.append("directly addable target")
    else:
        score -= 60
        reasons.append("not directly addable")

    if site_url:
        reasons.append("source available")

    return Candidate(raw=result, score=score, reasons=reasons)


def run_ranked_search(client: QBittorrentClient, config: dict[str, Any], query: str, limit: int = 5, plugins: str = "enabled") -> tuple[dict[str, Any], list[Candidate]]:
    title, year = parse_request(query)
    search_id = client.start_search(query, plugins=plugins)
    payload: dict[str, Any] = {"results": [], "total": 0, "status": "Running"}

    try:
        for _ in range(12):
            time.sleep(1)
            payload = client.get_search_results(search_id, limit=100, offset=0)
            if payload.get("status") in {"Stopped", "No Search Running"} or payload.get("results"):
                break
    finally:
        try:
            client.delete_search(search_id)
        except Exception:
            pass

    results = payload.get("results", [])
    ranked = sorted(
        (score_candidate(result, config, title, year) for result in results),
        key=lambda candidate: candidate.score,
        reverse=True,
    )[:limit]
    return payload, ranked


def format_bytes(size_bytes: int) -> str:
    if not size_bytes:
        return "unknown"
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size_bytes}B"


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
    match = re.search(r"(.+?)\s*\(?((?:19|20)\d{2})\)?\b", name)
    if match:
        raw_title = match.group(1)
        title = sanitize_name(re.sub(r"[\[(\s]+$", "", raw_title))
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


def freshclam_approval_command() -> str:
    return "sudo freshclam"


def run_freshclam_with_sudo() -> tuple[int, str, str]:
    return run_command(["sudo", "freshclam"])


def remove_junk_txt_files(root: Path) -> list[Path]:
    removed: list[Path] = []
    for path in root.rglob("*.txt"):
        lowered = path.name.lower().strip()
        if lowered in JUNK_TEXT_FILENAMES or lowered.startswith("downloaded from "):
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def remove_junk_image_files(root: Path) -> list[Path]:
    removed: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.name.lower().strip() in JUNK_IMAGE_FILENAMES:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def normalize_movie_folder(source: Path, keep_nfo: bool = True, remove_junk_txt: bool = True) -> tuple[Path, list[str]]:
    actions: list[str] = []
    work_root = source

    if source.is_file():
        title, year = infer_title_year(source.stem)
        folder_name = f"{title} ({year})" if year else title
        file_name = f"{title} ({year}){source.suffix.lower()}" if year else f"{title}{source.suffix.lower()}"
        normalized_root = source.parent / folder_name
        normalized_root.mkdir(exist_ok=True)
        desired_video = normalized_root / file_name
        if source != desired_video:
            source.rename(desired_video)
            actions.append(f"wrapped single file into folder {normalized_root.name}")
            actions.append(f"renamed video to {desired_video.name}")
        work_root = normalized_root

    if remove_junk_txt:
        removed = remove_junk_txt_files(work_root)
        if removed:
            actions.append(f"removed {len(removed)} junk txt file(s)")

    removed_images = remove_junk_image_files(work_root)
    if removed_images:
        actions.append(f"removed {len(removed_images)} junk image file(s)")

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


def copy_tree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob('*')):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def sudo_move_approval_command(source: Path, destination_parent: Path) -> str:
    destination = destination_parent / source.name
    src = str(source)
    dst = str(destination)
    src_q = shlex.quote(src)
    dst_q = shlex.quote(dst)
    return (
        f"sudo mkdir -p {dst_q} && "
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "import shutil\n"
        f"src = Path({src!r})\n"
        f"dst = Path({dst!r})\n"
        "dst.mkdir(parents=True, exist_ok=True)\n"
        "for path in sorted(src.rglob('*')):\n"
        "    rel = path.relative_to(src)\n"
        "    target = dst / rel\n"
        "    if path.is_dir():\n"
        "        target.mkdir(parents=True, exist_ok=True)\n"
        "    elif path.is_file():\n"
        "        target.parent.mkdir(parents=True, exist_ok=True)\n"
        "        shutil.copyfile(path, target)\n"
        "src_files = sorted(str(p.relative_to(src)) for p in src.rglob('*') if p.is_file())\n"
        "dst_files = sorted(str(p.relative_to(dst)) for p in dst.rglob('*') if p.is_file())\n"
        "print('MATCH' if src_files == dst_files else 'MISMATCH')\n"
        "PY\n"
        f"&& sudo chown -R jellyfin:jellyfin {dst_q} "
        f"&& sudo rm -r {src_q}"
    )


def safe_move(source: Path, destination_parent: Path) -> tuple[Path, list[str]]:
    actions: list[str] = []
    destination = destination_parent / source.name

    if destination.exists():
        if destination.is_dir() and source.is_dir() and verify_same_tree(source, destination):
            shutil.rmtree(source)
            actions.append("destination already contained verified copy")
            actions.append("removed original after verification")
            return destination, actions
        raise RuntimeError(f"Destination already exists: {destination}")

    same_device = source.stat().st_dev == destination_parent.stat().st_dev
    if same_device:
        source.rename(destination)
        actions.append("moved on same filesystem")
        return destination, actions

    try:
        copy_tree_contents(source, destination)
    except PermissionError as exc:
        raise PermissionError(f"Permission denied moving to {destination_parent}. Approval required: {sudo_move_approval_command(source, destination_parent)}") from exc
    except shutil.Error as exc:
        if any("Operation not permitted" in str(part) or "Permission denied" in str(part) for part in exc.args[0]):
            raise PermissionError(f"Permission denied moving to {destination_parent}. Approval required: {sudo_move_approval_command(source, destination_parent)}") from exc
        raise
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
