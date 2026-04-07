# Movie Agent

A chat-driven movie search, approval, download, scan, and post-processing toolkit built around qBittorrent and ClamAV.

## Current components
- `movie_agent_search.py` - search and rank releases from qBittorrent internal search
- `movie_agent_add.py` - preview or submit a chosen release to qBittorrent
- `movie_agent_postprocess.py` - scan, normalize, and safely move completed downloads
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
