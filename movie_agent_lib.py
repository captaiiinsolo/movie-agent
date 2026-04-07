#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

import tomllib

CONFIG_PATH = Path("/home/santos-family/.openclaw/workspace/movie-agent.config.toml")


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

    def start_search(self, pattern: str, category: str = "movies", plugins: str = "enabled") -> int:
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


def load_config() -> dict[str, Any]:
    return tomllib.loads(CONFIG_PATH.read_text())


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

    group_hits = [group for group in prefs.get("preferred_groups", []) if group.lower() in lower]
    if group_hits:
        score += 18
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

    if prefs.get("avoid_dual_audio") and "dual audio" in lower:
        score -= 25
        reasons.append("dual-audio penalty")

    if prefs.get("avoid_foreign_dub_unless_requested") and any(tag in lower for tag in ["dubbed", "french", "german", "ita", "spanish audio"]):
        score -= 40
        reasons.append("foreign-dub penalty")

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

    if any(reject.replace("_", " ") in lower for reject in filters):
        score -= 80
        reasons.append("matched reject filter")

    if site_url:
        reasons.append("source available")

    return Candidate(raw=result, score=score, reasons=reasons)


def run_ranked_search(client: QBittorrentClient, config: dict[str, Any], query: str, limit: int = 5) -> tuple[dict[str, Any], list[Candidate]]:
    title, year = parse_request(query)
    search_id = client.start_search(query)
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
