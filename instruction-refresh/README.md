# instruction-refresh

Keeps long-running Codex and Claude Code sessions aligned with their instruction files. The counter tracks every invocation and can trigger a refresh by turn count or by newly consumed tokens.

## Files

- `instruction-refresh-counter.sh` — public CLI, session state, thresholds, locking, and refresh output.
- `instruction-refresh-token-count.py` — internal JSONL parser used by token mode.

## Requirements

- Bash
- Python 3 for token mode
- Standard Linux tools including `flock`, `find`, `realpath`, and `base64`
- Exactly one active session ID: `CODEX_SESSION_ID` or `CLAUDE_CODE_SESSION_ID`

## Usage

```bash
./instruction-refresh-counter.sh \
  --mode tokens \
  --threshold 50000 \
  --instruction-file /path/to/AGENTS.md
```

Turn-based refresh:

```bash
./instruction-refresh-counter.sh \
  --mode turns \
  --threshold 20 \
  --instruction-file /path/to/AGENTS.md
```

Pass multiple instruction files as a comma-separated list. They are returned in the same order:

```bash
./instruction-refresh-counter.sh \
  --mode tokens \
  --threshold 50000 \
  --instruction-file /path/to/global.md,/path/to/project.md
```

Normal calls are silent until the threshold is reached. Use `--show-status` to print the counters on every call:

```text
turns=7/20 tokens=18420/50000 trigger=tokens refresh=no
```

When the active threshold is reached, the command prints the status and the current instruction-file contents:

```text
turns=0/20 tokens=0/50000 trigger=tokens refresh=yes state=reset
--- BEGIN INSTRUCTION REFRESH ---
<instruction contents>
--- END INSTRUCTION REFRESH ---
```

The counters reset after the instruction files have been read successfully. If a file cannot be read, the command fails without resetting them.

## Options

```text
--mode turns|tokens       Active refresh trigger
--threshold N             Positive threshold for the active mode
--instruction-file PATH   One path or a comma-separated path list
--show-status             Print status even when no refresh occurs
--reset                   Reset both counters without reading instructions
--log-file PATH           Override transcript discovery in token mode
--state-dir PATH          Override the state directory
--help                    Show CLI help
```

`--reset` still requires `--mode` and `--threshold`; it does not require `--instruction-file`.

## Token mode

On the first call, token mode anchors at the current end of the session transcript. Later calls count only new complete JSONL records.

- Codex counts uncached input plus output tokens from `token_count` events.
- Claude Code counts prompt growth across assistant messages and detects context compaction.
- Replaced, truncated, or incompatible transcripts restart the token cursor without back-counting old records.

The transcript is discovered under `$CODEX_HOME/sessions`, `~/.codex/sessions`, or `~/.claude/projects`. Set `INSTRUCTION_REFRESH_SESSIONS_DIR` or pass `--log-file` to override discovery.

## State

State is stored per platform session in `/tmp/instruction-refresh` with mode `0600` under a locked directory. Override the location with `INSTRUCTION_REFRESH_STATE_DIR` or `--state-dir`.

Run the counter once at the start of every assistant response. The calling agent is responsible for applying any instruction block returned by the command.
