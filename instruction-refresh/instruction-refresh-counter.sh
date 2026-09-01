#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: instruction-refresh-counter.sh --mode turns|tokens --threshold N --instruction-file PATH[,PATH...] [--show-status] [--reset] [--log-file PATH] [--state-dir PATH]" >&2
}

show_help() {
  cat <<'EOF'
usage: instruction-refresh-counter.sh --mode turns|tokens --threshold N --instruction-file PATH[,PATH...] [options]

Required for normal operation:
  --mode turns|tokens      Select the active refresh trigger.
  --threshold N            Set the active mode's positive threshold.
  --instruction-file PATH[,PATH...]
                            Return these files in order when the threshold is reached.

Options:
  --show-status             Return status even when no refresh occurs.
  --reset                   Reset both counters without reading instructions.
  --log-file PATH           Override the platform session JSONL in tokens mode.
  --state-dir PATH          Override the session-state directory.
  --help                    Show this help.

Output protocol:
  Normal operation is silent unless --show-status is used.
  A refresh returns a status line followed by:
    --- BEGIN INSTRUCTION REFRESH ---
    <instruction-file contents>
    --- END INSTRUCTION REFRESH ---
  A successful refresh resets both counters. A file-read failure resets neither.
EOF
}

default_turn_threshold=20
default_token_threshold=50000
refresh_mode=""
active_threshold=""
reset_counter=false
show_status=false
token_log_override=""
state_directory_override=""
instruction_file=""
script_directory=""
token_helper_file=""

while (($# > 0)); do
  case "$1" in
    --mode)
      if (($# < 2)); then
        usage
        exit 2
      fi
      refresh_mode=$2
      shift 2
      ;;
    --threshold)
      if (($# < 2)); then
        usage
        exit 2
      fi
      active_threshold=$2
      shift 2
      ;;
    --reset)
      reset_counter=true
      shift
      ;;
    --instruction-file)
      if (($# < 2)); then
        usage
        exit 2
      fi
      instruction_file=$2
      shift 2
      ;;
    --show-status)
      show_status=true
      shift
      ;;
    --log-file)
      if (($# < 2)); then
        usage
        exit 2
      fi
      token_log_override=$2
      shift 2
      ;;
    --state-dir)
      if (($# < 2)); then
        usage
        exit 2
      fi
      state_directory_override=$2
      shift 2
      ;;
    --help)
      show_help
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ $refresh_mode != turns && $refresh_mode != tokens ]]; then
  echo "error: --mode must be turns or tokens" >&2
  exit 2
fi
if [[ ! $active_threshold =~ ^[1-9][0-9]*$ ]]; then
  echo "error: --threshold must be a positive integer" >&2
  exit 2
fi
if [[ $refresh_mode == turns && -n $token_log_override ]]; then
  echo "error: --log-file is valid only in tokens mode" >&2
  exit 2
fi
if ! $reset_counter && [[ -z $instruction_file ]]; then
  echo "error: --instruction-file is required for normal operation" >&2
  exit 2
fi

refresh_platform=""
refresh_session_id=""
if [[ -n ${CODEX_SESSION_ID:-} && -n ${CLAUDE_CODE_SESSION_ID:-} ]]; then
  echo "error: multiple platform session IDs are set; cannot determine the current platform" >&2
  exit 2
elif [[ -n ${CODEX_SESSION_ID:-} ]]; then
  refresh_platform=codex
  refresh_session_id=$CODEX_SESSION_ID
elif [[ -n ${CLAUDE_CODE_SESSION_ID:-} ]]; then
  refresh_platform=claude
  refresh_session_id=$CLAUDE_CODE_SESSION_ID
else
  echo "error: no supported platform session ID is available" >&2
  exit 2
fi
if [[ ! $refresh_session_id =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "error: platform session ID contains unsupported characters" >&2
  exit 2
fi

default_state_directory=/tmp/instruction-refresh
refresh_state_directory=${state_directory_override:-${INSTRUCTION_REFRESH_STATE_DIR:-$default_state_directory}}

umask 077
mkdir -p -- "$refresh_state_directory"
refresh_state_directory=$(cd -- "$refresh_state_directory" && pwd -P)
refresh_state_file="$refresh_state_directory/${refresh_platform}-session-state-$refresh_session_id.json"

exec {refresh_lock_fd}<"$refresh_state_directory"
flock -x "$refresh_lock_fd"

stored_session_id=""
stored_mode=""
stored_turn_counter=""
stored_turn_threshold=""
stored_token_counter=""
stored_token_threshold=""
stored_token_cursor_b64=""
stored_log_file_b64=""
state_status=""

if [[ -f $refresh_state_file ]]; then
  stored_session_id=$(sed -n 's/.*"session_id": "\([^"]*\)".*/\1/p' "$refresh_state_file" | head -n 1)
  stored_mode=$(sed -n 's/.*"mode": "\([^"]*\)".*/\1/p' "$refresh_state_file" | head -n 1)
  stored_turn_counter=$(sed -n 's/.*"turn_counter": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
  stored_turn_threshold=$(sed -n 's/.*"turn_threshold": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
  stored_token_counter=$(sed -n 's/.*"token_counter": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
  stored_token_threshold=$(sed -n 's/.*"token_threshold": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
  stored_token_cursor_b64=$(sed -n 's/.*"token_cursor_b64": "\([^"]*\)".*/\1/p' "$refresh_state_file" | head -n 1)
  stored_log_file_b64=$(sed -n 's/.*"log_file_b64": "\([^"]*\)".*/\1/p' "$refresh_state_file" | head -n 1)
fi

if [[ ! -f $refresh_state_file ]]; then
  stored_session_id=$refresh_session_id
  stored_mode=$refresh_mode
  stored_turn_counter=0
  stored_turn_threshold=$default_turn_threshold
  stored_token_counter=0
  stored_token_threshold=$default_token_threshold
  stored_token_cursor_b64=""
  stored_log_file_b64=""
  state_status=" state=initialized"
elif [[ $stored_session_id == "$refresh_session_id" && $stored_mode == turns && $stored_turn_counter =~ ^[0-9]+$ && $stored_turn_threshold =~ ^[1-9][0-9]*$ ]]; then
  stored_token_counter=0
  stored_token_threshold=$default_token_threshold
  stored_token_cursor_b64=""
  stored_log_file_b64=""
elif [[ $stored_session_id == "$refresh_session_id" && $stored_mode == tokens && $stored_turn_counter =~ ^[0-9]+$ && $stored_turn_threshold =~ ^[1-9][0-9]*$ && $stored_token_counter =~ ^[0-9]+$ && $stored_token_threshold =~ ^[1-9][0-9]*$ && -n $stored_token_cursor_b64 && -n $stored_log_file_b64 ]]; then
  :
else
  stored_session_id=$refresh_session_id
  stored_mode=$refresh_mode
  stored_turn_counter=0
  stored_turn_threshold=$default_turn_threshold
  stored_token_counter=0
  stored_token_threshold=$default_token_threshold
  stored_token_cursor_b64=""
  stored_log_file_b64=""
  state_status=" state=restarted"
fi

turn_counter=$stored_turn_counter
turn_threshold=$stored_turn_threshold
token_counter=$stored_token_counter
token_threshold=$stored_token_threshold
token_cursor_b64=$stored_token_cursor_b64
log_file_b64=$stored_log_file_b64
previous_mode=$stored_mode

if [[ $refresh_mode == turns ]]; then
  turn_threshold=$active_threshold
else
  token_threshold=$active_threshold
fi

token_log_file=""
resolved_log_file_b64=""

find_token_log() {
  if [[ -n $token_log_override ]]; then
    token_log_file=$token_log_override
  elif [[ -n $log_file_b64 ]]; then
    if ! token_log_file=$(printf '%s' "$log_file_b64" | base64 --decode 2>/dev/null); then
      token_log_file=""
    fi
    if [[ ! -f $token_log_file || ! -r $token_log_file ]]; then
      token_log_file=""
    fi
  fi

  if [[ -z $token_log_file ]]; then
    matching_logs=()
    if [[ -n ${INSTRUCTION_REFRESH_SESSIONS_DIR:-} ]]; then
      sessions_directory=$INSTRUCTION_REFRESH_SESSIONS_DIR
    elif [[ $refresh_platform == codex && -n ${CODEX_HOME:-} ]]; then
      sessions_directory=$CODEX_HOME/sessions
    elif [[ $refresh_platform == codex && -n ${HOME:-} ]]; then
      sessions_directory=$HOME/.codex/sessions
    elif [[ $refresh_platform == claude && -n ${HOME:-} ]]; then
      sessions_directory=$HOME/.claude/projects
    else
      echo "error: cannot locate the sessions directory" >&2
      exit 2
    fi

    if [[ ! -d $sessions_directory ]]; then
      echo "error: sessions directory does not exist: $sessions_directory" >&2
      exit 2
    fi

    if [[ $refresh_platform == codex ]]; then
      mapfile -d '' matching_logs < <(
        find "$sessions_directory" -type f -name "*$refresh_session_id*.jsonl" -print0
      )
    else
      mapfile -d '' matching_logs < <(
        find "$sessions_directory" -type f -name "$refresh_session_id.jsonl" -print0
      )
    fi
    if ((${#matching_logs[@]} == 0)); then
      echo "error: no session JSONL found for $refresh_session_id" >&2
      exit 2
    fi
    if ((${#matching_logs[@]} > 1)); then
      echo "error: multiple session JSONL files found for $refresh_session_id" >&2
      exit 2
    fi
    token_log_file=${matching_logs[0]}
  fi

  if [[ ! -f $token_log_file || ! -r $token_log_file ]]; then
    echo "error: token log is not a readable file: $token_log_file" >&2
    exit 2
  fi
  resolved_log_file_b64=$(printf '%s' "$token_log_file" | base64 --wrap=0)
}

require_token_helper() {
  if [[ -z $token_helper_file ]]; then
    script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
    token_helper_file="$script_directory/instruction-refresh-token-count.py"
  fi
  if [[ ! -f $token_helper_file || ! -r $token_helper_file ]]; then
    echo "error: token helper is not readable: $token_helper_file" >&2
    exit 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 is required for token counting" >&2
    exit 1
  fi
}

parse_token_helper_output() {
  helper_output=$1

  if [[ $helper_output == *$'\n'* ]]; then
    echo "error: token helper returned multiple output lines" >&2
    exit 1
  fi

  helper_protocol=""
  helper_token_delta=""
  helper_event_count=""
  helper_next_cursor_b64=""
  helper_status=""
  helper_extra=""
  read -r helper_protocol helper_token_delta helper_event_count \
    helper_next_cursor_b64 helper_status helper_extra <<<"$helper_output"

  if [[ $helper_protocol != v1 \
        || ! $helper_token_delta =~ ^[0-9]+$ \
        || ! $helper_event_count =~ ^[0-9]+$ \
        || ! $helper_next_cursor_b64 =~ ^[A-Za-z0-9_-]+={0,2}$ \
        || ! $helper_status =~ ^(anchored|ok|restarted|compacted)$ \
        || -n $helper_extra ]]; then
    echo "error: token helper returned invalid output" >&2
    exit 1
  fi
}

anchor_token_log() {
  require_token_helper
  helper_output=""
  if ! helper_output=$(
    python3 "$token_helper_file" anchor \
      --platform "$refresh_platform" \
      --log-file "$token_log_file"
  ); then
    exit 1
  fi
  parse_token_helper_output "$helper_output"

  if [[ $helper_status != anchored \
        || $helper_token_delta != 0 \
        || $helper_event_count != 0 ]]; then
    echo "error: token helper returned an invalid anchor result" >&2
    exit 1
  fi
  token_cursor_b64=$helper_next_cursor_b64
}

scan_token_log() {
  require_token_helper
  helper_output=""
  if ! helper_output=$(
    python3 "$token_helper_file" scan \
      --platform "$refresh_platform" \
      --log-file "$token_log_file" \
      --cursor "$token_cursor_b64"
  ); then
    exit 1
  fi
  parse_token_helper_output "$helper_output"

  if [[ $helper_status == anchored ]]; then
    echo "error: token helper returned an anchor result for a scan" >&2
    exit 1
  fi

  if [[ $helper_status == restarted ]]; then
    token_counter=0
    state_status=" state=restarted"
  elif [[ $helper_status == compacted ]]; then
    token_counter=0
    state_status=" state=compacted"
  fi
  token_counter=$((token_counter + helper_token_delta))
  token_cursor_b64=$helper_next_cursor_b64
}

if $reset_counter; then
  turn_counter=0
  token_counter=0
  if [[ $refresh_mode == tokens ]]; then
    find_token_log
    log_file_b64=$resolved_log_file_b64
    anchor_token_log
  fi
  state_status=" state=reset"
else
  turn_counter=$((turn_counter + 1))

  if [[ $refresh_mode == turns && $previous_mode != turns ]]; then
    state_status=" state=mode-changed"
  elif [[ $refresh_mode == tokens ]]; then
    find_token_log
    log_file_b64=$resolved_log_file_b64

    if [[ $previous_mode != tokens || -z $token_cursor_b64 ]]; then
      token_counter=0
      anchor_token_log
      if [[ $previous_mode != tokens ]]; then
        state_status=" state=mode-changed"
      fi
    else
      scan_token_log
    fi
  fi
fi

stored_mode=$refresh_mode
refresh_required=no
if [[ $refresh_mode == turns && $turn_counter -ge $turn_threshold ]]; then
  refresh_required=yes
elif [[ $refresh_mode == tokens && $token_counter -ge $token_threshold ]]; then
  refresh_required=yes
fi

instruction_contents=""
instruction_file_resolved=""
refresh_completed=no
if [[ $refresh_required == yes ]]; then
  if [[ $instruction_file == ,* || $instruction_file == *, || $instruction_file == *,,* ]]; then
    echo "error: instruction file list contains an empty path" >&2
    exit 1
  fi
  IFS=',' read -r -a instruction_files <<<"$instruction_file"
  for instruction_file_entry in "${instruction_files[@]}"; do
    if [[ ! -f $instruction_file_entry || ! -r $instruction_file_entry ]]; then
      echo "error: instruction file is not readable: $instruction_file_entry" >&2
      exit 1
    fi
    instruction_file_resolved=$(realpath -- "$instruction_file_entry")
    current_instruction_contents=$(<"$instruction_file_resolved")
    if [[ -z $current_instruction_contents ]]; then
      echo "error: instruction file is empty: $instruction_file_resolved" >&2
      exit 1
    fi
    if [[ -n $instruction_contents ]]; then
      instruction_contents+=$'\n'
    fi
    instruction_contents+=$current_instruction_contents
  done

  refresh_completed=yes
  turn_counter=0
  token_counter=0
  if [[ $refresh_mode == tokens ]]; then
    anchor_token_log
  fi
  state_status=" state=reset"
fi

umask 077
temporary_state_file=$(mktemp "$refresh_state_directory/.instruction-refresh-state.XXXXXX")
cleanup_temporary_state() {
  if [[ -n ${temporary_state_file:-} && -f $temporary_state_file ]]; then
    rm -f -- "$temporary_state_file"
  fi
}
trap cleanup_temporary_state EXIT

if [[ $refresh_mode == turns ]]; then
  printf '{\n  "session_id": "%s",\n  "mode": "turns",\n  "turn_counter": %d,\n  "turn_threshold": %d\n}\n' \
    "$refresh_session_id" "$turn_counter" "$turn_threshold" >"$temporary_state_file"
else
  printf '{\n  "session_id": "%s",\n  "mode": "tokens",\n  "turn_counter": %d,\n  "turn_threshold": %d,\n  "token_counter": %d,\n  "token_threshold": %d,\n  "token_cursor_b64": "%s",\n  "log_file_b64": "%s"\n}\n' \
    "$refresh_session_id" "$turn_counter" "$turn_threshold" "$token_counter" "$token_threshold" "$token_cursor_b64" "$log_file_b64" >"$temporary_state_file"
fi
mv -f -- "$temporary_state_file" "$refresh_state_file"
temporary_state_file=""

if $show_status || [[ $refresh_completed == yes ]]; then
  if [[ $refresh_mode == turns ]]; then
    echo "turns=$turn_counter/$turn_threshold trigger=turns refresh=$refresh_required$state_status"
  else
    echo "turns=$turn_counter/$turn_threshold tokens=$token_counter/$token_threshold trigger=tokens refresh=$refresh_required$state_status"
  fi
fi

if [[ $refresh_completed == yes ]]; then
  echo "--- BEGIN INSTRUCTION REFRESH ---"
  printf '%s\n' "$instruction_contents"
  echo "--- END INSTRUCTION REFRESH ---"
fi
