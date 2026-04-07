# Movie Agent

A chat-driven movie search, approval, download, scan, and post-processing toolkit built around qBittorrent and ClamAV.

## Current components
- `movie_agent_search.py` - search and rank releases from qBittorrent internal search
- `movie_agent_add.py` - preview or submit a chosen release to qBittorrent
- `movie_agent_postprocess.py` - scan, normalize, and safely move completed downloads
- `movie_agent_pick.py` - normal-use wrapper for seed-sorted manual choice flow
- `movie_agent_lib.py` - shared config/API/ranking logic

## Config
Copy:
- `movie-agent.config.example.toml`

to a private local file such as:
- `movie-agent.config.toml`

Then fill in local secrets like the qBittorrent password privately.

## Notes
This project is intended to grow into a full Option A movie agent:
- human-approved selection before download
- automated post-processing after approval
- ClamAV safety gate before moving media into the library

## Normal-use flow
Show seed-sorted, addable results for manual choice:

```bash
python3 movie_agent_pick.py "Toy Story 1995"
```

Submit a displayed choice:

```bash
python3 movie_agent_pick.py "Toy Story 1995" --choice 1 --download
```

Submit and wait for completion:

```bash
python3 movie_agent_pick.py "Toy Story 1995" --choice 1 --download --wait
```

## Live chat scaffolding
For a Telegram/OpenClaw conversation flow, use:

```bash
python3 movie_agent_live.py search "Toy Story 1995"
python3 movie_agent_live.py choose 1
```

This stores lightweight session state in:

- `state/live_state.json`

That gives the chat agent a stable contract for:
- latest query
- displayed options
- selected option
- confirmation handoff
