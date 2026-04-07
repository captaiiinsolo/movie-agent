# Movie Agent OpenClaw / Telegram Integration

## Goal
Turn the movie-agent into a live chat workflow for Solo on Telegram with strong approvals and predictable state.

## Recommended runtime contract
Use these scripts as the stable integration surface:

- `movie_agent_dispatch.py` - message-level dispatcher for chat input
- `movie_agent_live.py` - stateful search/choice helper
- `movie_agent_pick.py` - normal backend flow with seed-sorted manual choice
- `movie_agent_postprocess.py` - explicit postprocess fallback when needed

## Suggested chat flow

### 1. User sends a movie request
Examples:
- `Toy Story 1995`
- `download Mulan 1998`
- `find Heat 1995`

Integration action:
```bash
python3 movie_agent_dispatch.py "<user message>"
```

Expected behavior:
- treats non-control text as a movie search
- stores options in `state/live_state.json`
- replies with numbered options

### 2. User replies with a number
Example:
- `1`

Integration action:
```bash
python3 movie_agent_dispatch.py "1"
```

Expected behavior:
- stores selected choice
- replies with selected release
- asks for yes/no confirmation

### 3. User confirms
Examples:
- `yes`
- `go ahead`

Integration action:
```bash
python3 movie_agent_dispatch.py "yes"
```

Expected behavior:
- runs `movie_agent_pick.py <query> --choice <n> --download --wait`
- reports milestones through stdout

## State file
Live chat state is stored in:
- `state/live_state.json`

Current fields:
- `query`
- `results_seen`
- `options`
- `selected_choice`
- `selected_name`

## v1 operating rules
- Single-user only
- No download without explicit confirmation
- `sudo freshclam` remains approval-gated
- privileged move remains approval-gated
- if state is confusing, send `clear` or `cancel`

## Operator notes
This integration layer is intentionally conservative.
It is designed so OpenClaw can map Telegram messages into a deterministic local command without inventing state itself.

## Example manual simulation
```bash
python3 movie_agent_dispatch.py "Toy Story 1995"
python3 movie_agent_dispatch.py "1"
python3 movie_agent_dispatch.py "yes"
```
