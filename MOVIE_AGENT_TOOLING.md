# Movie Agent Tooling

## Current local tools
- `movie_agent_search.py`
- `movie_agent_add.py`
- `movie_agent_postprocess.py`
- `movie_agent_lib.py`

## Purpose
These tools read `movie-agent.config.toml`, log into qBittorrent Web UI/API, run movie searches through qBittorrent's internal search engine, and rank returned results using Solo's current preferences.

## Search example
```bash
python3 /home/santos-family/.openclaw/workspace/movie_agent_search.py "Beethoven 1992" --limit 5
```

## Choose-and-submit example
Preview only, no download started:
```bash
python3 /home/santos-family/.openclaw/workspace/movie_agent_add.py "Beethoven 1992" --choice 1 --limit 3
```

Actually submit the chosen result to qBittorrent:
```bash
python3 /home/santos-family/.openclaw/workspace/movie_agent_add.py "Beethoven 1992" --choice 1 --limit 3 --approve
```

## Postprocess example
Preview scan + rename logic without moving:
```bash
python3 /home/santos-family/.openclaw/workspace/movie_agent_postprocess.py --path "/path/to/completed/download" --allow-stale-db
```

Actually move after scan + normalization:
```bash
python3 /home/santos-family/.openclaw/workspace/movie_agent_postprocess.py --path "/path/to/completed/download" --allow-stale-db --move
```

## Current behavior
- logs into qBittorrent locally
- starts a search job
- collects results
- ranks results by title/year, resolution, codec, size, seed health, and preference rules
- prints top candidates in a human-readable format
- supports explicit choose-and-submit workflow with a safe preview default
- supports scan + rename + safe cross-filesystem move workflow with preview mode

## Notes
- Uses the real local config file: `movie-agent.config.toml`
- Does not print the qBittorrent password
- This is the first building block for the full movie agent workflow
