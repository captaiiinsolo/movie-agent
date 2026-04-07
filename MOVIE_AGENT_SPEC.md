# Movie Agent Spec

## Goal
A chat-driven movie download agent that helps Solo find, approve, download, scan, clean, and move movie releases with strong safety boundaries.

## Mode
Option A: human-in-the-loop selection.

The agent must always ask for approval before starting a download.
After approval, it may automate the rest unless ambiguity or a safety problem appears.

## Config
Primary local config:
- `movie-agent.config.toml`

Safe template:
- `movie-agent.config.example.toml`

The real config contains qBittorrent credentials and must not be exposed in chat or committed.

## High-level workflow

### 1. Intake
The user sends a request such as:
- `download Beethoven 1992`
- `find Heat 1995`
- `grab The Nice Guys in 1080p`

The agent extracts:
- title
- optional year
- optional quality override
- optional special preferences for this request

### 2. Search
The agent searches candidate releases from the configured/approved search source.

The search layer is expected to return enough metadata to rank candidates, including when available:
- title
- year
- resolution
- video codec
- audio details
- subtitle details
- release group
- size
- seeders
- leechers
- magnet link or torrent link

### 3. Filtering
The agent rejects candidates that match disallowed classes, including:
- CAM
- TS / telesync
- screeners
- passworded archives
- AV1
- obvious junk releases
- ambiguous title/year matches
- foreign-dub releases unless requested
- dual-audio clutter when avoidable
- 4K unless no good alternative exists and explicit approval is obtained

### 4. Ranking
The agent ranks candidates using these default priorities:

1. correct title/year match
2. preferred release groups: YIFY, BONES
3. 1080p preferred
4. 720p acceptable fallback
5. x264 preferred
6. x265 / HEVC acceptable
7. avoid AV1
8. efficient size
9. strongest audio quality
10. English subtitles only or best English-sub support
11. healthier seeder / leecher profile
12. avoid absurdly large encodes

Notes:
- Preferred groups are a strong preference, not an absolute rule.
- A non-YIFY/BONES release may outrank them if it is materially better and still fits Solo's preferences.

### 5. Approval step
Before any download starts, the agent presents the best 1 to 3 options.

For each option, show:
- release name
- resolution
- codec
- size
- audio summary
- subtitle summary if known
- seeder/leecher snapshot
- release group
- why it was chosen

The agent asks the user to approve one option.
No download starts without approval.

### 6. qBittorrent handoff
After approval, the agent submits the selected release to qBittorrent using the Web UI/API.

Configured values come from `movie-agent.config.toml`.

The agent should:
- authenticate to qBittorrent
- submit magnet or torrent
- capture success/failure
- report that the download was accepted or explain the failure clearly

### 7. Monitor completion
The agent monitors qBittorrent for completion status.

When the approved item finishes downloading, the agent identifies the completed file/folder in the configured downloads path.

If the completed result is ambiguous, the agent pauses and asks the user.

### 8. Malware scan gate
Before moving anything to the media drive, the agent must run a scan gate.

Required sequence:
1. run `clamscan` on the completed download target
2. if the virus database is stale or the scan environment indicates definitions should be refreshed, ask for approval and run `sudo freshclam`
3. run `clamscan` again
4. only continue if the result is clean

If scanning fails, the agent must stop and report the problem.
It must not move the download to the media drive after a failed or inconclusive scan.

### 9. Post-processing
If the scan passes, the agent may automatically:
- strip tracker junk from folder/file names
- keep `.nfo` files
- remove junk `.txt` tracker files if configured
- normalize the directory and filename

Default naming target:
- folder: `{title} ({year})`
- file: `{title} ({year})`

Example:
- `Beethoven (1992)/Beethoven (1992).mp4`

### 10. Move to library
After successful post-processing, move the completed movie into:
- `/mnt/th3keyMedia/Movies`

This should be a real move, not a quiet duplicate left behind in Downloads.
If the move crosses filesystems, the agent must verify the destination contents and only then remove the source copy.

### 11. Final report
The agent sends a completion summary including:
- selected release name
- whether scan passed cleanly
- final destination path
- any cleanup actions performed
- any issues or manual follow-up needed

## Safety rules
- Always require approval before download starts.
- Ask again if title/year match confidence is low.
- Ask again if only 4K options exist and no good 1080p/720p option is available.
- Ask again if `sudo freshclam` is needed.
- Do not silently delete source files until destination integrity is confirmed.
- Do not expose qBittorrent credentials in chat output.

## Future extensions
Possible future improvements:
- metadata/artwork fetching
- Jellyfin-friendly NFO/poster generation
- better source-specific ranking rules
- TV/movie auto-classification
- direct quality profiles by requester intent
