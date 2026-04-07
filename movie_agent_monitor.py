#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from movie_agent_lib import build_client, db_older_than_days, load_config, scan_path

STATE_PATH = Path('/home/santos-family/.openclaw/workspace/movie-agent/state/monitor_state.json')
THRESHOLDS = [25, 50, 75, 100]


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"tracked": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def send_message(target: str, message: str) -> None:
    subprocess.run(
        [
            'openclaw', 'message', 'send',
            '--channel', 'telegram',
            '--target', target,
            '--message', message,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def track_torrent(hash_value: str, name: str, notify_target: str, content_path: str | None = None) -> None:
    state = load_state()
    tracked = state.setdefault('tracked', {})
    tracked[hash_value] = {
        'name': name,
        'notify_target': notify_target,
        'content_path': content_path or '',
        'sent': [],
        'scan_sent': False,
        'start_sent': False,
        'move_started_sent': False,
        'move_completed_sent': False,
        'done': False,
    }
    save_state(state)


def monitor_once() -> int:
    state = load_state()
    tracked = state.setdefault('tracked', {})
    if not tracked:
        print('No tracked torrents.')
        return 0

    config = load_config()
    client = build_client(config)
    client.login()
    torrents = {item.get('hash'): item for item in client.list_torrents('all') if item.get('hash')}

    changed = False
    for hash_value, item in list(tracked.items()):
        torrent = torrents.get(hash_value)
        name = item.get('name') or hash_value
        target = item.get('notify_target')
        sent = set(item.get('sent') or [])

        if torrent is not None:
            progress = float(torrent.get('progress') or 0)
            state_name = torrent.get('state') or 'unknown'
            item['content_path'] = torrent.get('content_path') or item.get('content_path') or ''
            if not item.get('start_sent'):
                send_message(target, f'Download started: {name}')
                item['start_sent'] = True
                changed = True
            for threshold in THRESHOLDS:
                if progress >= threshold / 100 and threshold not in sent:
                    send_message(target, f'{name}: {threshold}% complete ({state_name})')
                    sent.add(threshold)
                    changed = True
            item['sent'] = sorted(sent)
            if progress >= 1.0 or state_name in {'uploading', 'stalledUP', 'queuedUP', 'forcedUP'}:
                item['done'] = True
        elif item.get('done') and not item.get('scan_sent'):
            content_path = Path(item.get('content_path') or '')
            if content_path.exists():
                clean, stale_by_scan, _scan_log = scan_path(content_path)
                stale = stale_by_scan or db_older_than_days(7)
                status = 'clean' if clean else 'failed'
                suffix = ' (definitions stale)' if stale else ''
                send_message(target, f'ClamAV scan {status} for {content_path.name}{suffix}')
                item['scan_sent'] = True
                changed = True

        candidates = []
        content_path_value = item.get('content_path') or ''
        if content_path_value:
            cp = Path(content_path_value)
            candidates.append(cp.with_suffix(''))
            stem_title = cp.stem.replace('.', ' ').replace('_', ' ')
            import re
            m = re.search(r'(.+?)\s*((19|20)\d{2})', stem_title)
            if m:
                candidates.append(Path('/home/santos-family/Downloads') / f"{m.group(1).strip()} ({m.group(2)})")
                candidates.append(Path('/mnt/th3keyMedia/Movies') / f"{m.group(1).strip()} ({m.group(2)})")

        normalized_dir = next((p for p in candidates if p.exists() and p.is_dir() and str(p).startswith('/home/santos-family/Downloads')), None)
        if item.get('scan_sent') and not item.get('move_started_sent') and normalized_dir is not None:
            send_message(target, f'Move starting: {normalized_dir.name}')
            item['move_started_sent'] = True
            changed = True

        movies_match = [p for p in candidates if p.exists() and p.is_dir() and str(p).startswith('/mnt/th3keyMedia/Movies')]
        if item.get('move_started_sent') and not item.get('move_completed_sent') and movies_match:
            send_message(target, f'Move complete: {movies_match[0].name}')
            item['move_completed_sent'] = True
            changed = True

        if item.get('scan_sent'):
            item['inactive'] = True

    if changed:
        save_state(state)
    print('Monitor pass complete.')
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Durable movie torrent monitor for progress and scan notifications.')
    sub = parser.add_subparsers(dest='cmd', required=True)

    track = sub.add_parser('track')
    track.add_argument('--hash', required=True)
    track.add_argument('--name', required=True)
    track.add_argument('--notify-target', required=True)
    track.add_argument('--content-path')

    sub.add_parser('run-once')

    args = parser.parse_args()
    if args.cmd == 'track':
        track_torrent(args.hash, args.name, args.notify_target, args.content_path)
        print(f'Tracking {args.name} ({args.hash})')
        return 0
    return monitor_once()


if __name__ == '__main__':
    raise SystemExit(main())
