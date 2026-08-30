#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: instruction-refresh-counter.sh --mode turns|tokens --threshold N [--reset] [--log-file PATH] [--state-dir PATH]" >&2
}

default_turn_threshold=20
default_token_threshold=50000
refresh_mode=""
active_threshold=""
reset_counter=false
token_log_override=""
state_directory_override=""

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

if [[ $refresh_mode == tokens && $refresh_platform != codex ]]; then
  echo "error: tokens mode is not supported on $refresh_platform" >&2
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
stored_log_offset=""
stored_log_file_b64=""
legacy_counter=""
state_status=""

if [[ -f $refresh_state_file ]]; then
  stored_session_id=$(sed -n 's/.*"session_id": "\([^"]*\)".*/\1/p' "$refresh_state_file" | head -n 1)
  stored_mode=$(sed -n 's/.*"mode": "\([^"]*\)".*/\1/p' "$refresh_state_file" | head -n 1)
  stored_turn_counter=$(sed -n 's/.*"turn_counter": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
  stored_turn_threshold=$(sed -n 's/.*"turn_threshold": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
  stored_token_counter=$(sed -n 's/.*"token_counter": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
  stored_token_threshold=$(sed -n 's/.*"token_threshold": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
  stored_log_offset=$(sed -n 's/.*"log_offset": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
  stored_log_file_b64=$(sed -n 's/.*"log_file_b64": "\([^"]*\)".*/\1/p' "$refresh_state_file" | head -n 1)
  legacy_counter=$(sed -n 's/.*"counter": \([0-9][0-9]*\).*/\1/p' "$refresh_state_file" | head -n 1)
fi

if [[ ! -f $refresh_state_file ]]; then
  stored_session_id=$refresh_session_id
  stored_mode=$refresh_mode
  stored_turn_counter=0
  stored_turn_threshold=$default_turn_threshold
  stored_token_counter=0
  stored_token_threshold=$default_token_threshold
  stored_log_offset=0
  stored_log_file_b64=""
  state_status=" state=initialized"
elif [[ $stored_session_id == "$refresh_session_id" && $stored_mode == turns && $stored_turn_counter =~ ^[0-9]+$ && $stored_turn_threshold =~ ^[1-9][0-9]*$ ]]; then
  stored_token_counter=0
  stored_token_threshold=$default_token_threshold
  stored_log_offset=0
  stored_log_file_b64=""
elif [[ $stored_session_id == "$refresh_session_id" && $stored_mode == tokens && $stored_turn_counter =~ ^[0-9]+$ && $stored_turn_threshold =~ ^[1-9][0-9]*$ && $stored_token_counter =~ ^[0-9]+$ && $stored_token_threshold =~ ^[1-9][0-9]*$ && $stored_log_offset =~ ^[0-9]+$ ]]; then
  :
elif [[ $stored_session_id == "$refresh_session_id" && $stored_mode =~ ^(turns|tokens)$ && $legacy_counter =~ ^[0-9]+$ ]]; then
  stored_turn_counter=0
  stored_turn_threshold=$default_turn_threshold
  stored_token_counter=0
  stored_token_threshold=$default_token_threshold
  if [[ $stored_mode == turns ]]; then
    stored_turn_counter=$legacy_counter
  else
    stored_token_counter=$legacy_counter
  fi
  if [[ ! $stored_log_offset =~ ^[0-9]+$ ]]; then
    stored_log_offset=0
  fi
  state_status=" state=migrated"
else
  stored_session_id=$refresh_session_id
  stored_mode=$refresh_mode
  stored_turn_counter=0
  stored_turn_threshold=$default_turn_threshold
  stored_token_counter=0
  stored_token_threshold=$default_token_threshold
  stored_log_offset=0
  stored_log_file_b64=""
  state_status=" state=restarted"
fi

turn_counter=$stored_turn_counter
turn_threshold=$stored_turn_threshold
token_counter=$stored_token_counter
token_threshold=$stored_token_threshold
log_offset=$stored_log_offset
log_file_b64=$stored_log_file_b64
previous_mode=$stored_mode

if [[ $refresh_mode == turns ]]; then
  turn_threshold=$active_threshold
else
  token_threshold=$active_threshold
fi

token_log_file=""
token_log_size=0
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
    elif [[ -n ${CODEX_HOME:-} ]]; then
      sessions_directory=$CODEX_HOME/sessions
    elif [[ -n ${HOME:-} ]]; then
      sessions_directory=$HOME/.codex/sessions
    else
      echo "error: cannot locate the sessions directory" >&2
      exit 2
    fi

    if [[ ! -d $sessions_directory ]]; then
      echo "error: sessions directory does not exist: $sessions_directory" >&2
      exit 2
    fi

    mapfile -d '' matching_logs < <(
      find "$sessions_directory" -type f -name "*$refresh_session_id*.jsonl" -print0
    )
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
  token_log_size=$(stat -c %s -- "$token_log_file")
  resolved_log_file_b64=$(printf '%s' "$token_log_file" | base64 --wrap=0)
}

if $reset_counter; then
  if [[ $refresh_mode == turns ]]; then
    turn_counter=0
  else
    find_token_log
    token_counter=0
    log_offset=$token_log_size
    log_file_b64=$resolved_log_file_b64
  fi
  state_status=" state=reset"
else
  turn_counter=$((turn_counter + 1))

  if [[ $refresh_mode == turns && $previous_mode != turns ]]; then
    state_status=" state=mode-changed"
  elif [[ $refresh_mode == tokens ]]; then
    find_token_log
    log_file_b64=$resolved_log_file_b64

    if [[ $previous_mode != tokens ]]; then
      token_counter=0
      log_offset=$token_log_size
      state_status=" state=mode-changed"
    elif ((log_offset > token_log_size)); then
      token_counter=0
      log_offset=$token_log_size
      state_status=" state=restarted"
    else
      unread_byte_count=$((token_log_size - log_offset))
      if ((unread_byte_count > 0)); then
        token_event_count=$(
          dd if="$token_log_file" iflag=skip_bytes,count_bytes skip="$log_offset" count="$unread_byte_count" status=none |
            grep -c '"type":"token_count"' || true
        )
        read -r token_delta parsed_event_count < <(
          dd if="$token_log_file" iflag=skip_bytes,count_bytes skip="$log_offset" count="$unread_byte_count" status=none |
            sed -nE '/"type":"token_count"/ s/.*"last_token_usage":\{"input_tokens":([0-9]+),"cached_input_tokens":([0-9]+),"cache_write_input_tokens":[0-9]+,"output_tokens":([0-9]+).*/\1 \2 \3/p' |
            awk '{ delta += $1 - $2 + $3; parsed += 1 } END { printf "%d %d\n", delta, parsed }'
        )

        if [[ $token_event_count != "$parsed_event_count" ]]; then
          echo "error: an unrecognized token_count event was encountered" >&2
          exit 1
        fi

        token_counter=$((token_counter + token_delta))
        log_offset=$token_log_size
      fi
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
  printf '{\n  "session_id": "%s",\n  "mode": "tokens",\n  "turn_counter": %d,\n  "turn_threshold": %d,\n  "token_counter": %d,\n  "token_threshold": %d,\n  "log_offset": %d,\n  "log_file_b64": "%s"\n}\n' \
    "$refresh_session_id" "$turn_counter" "$turn_threshold" "$token_counter" "$token_threshold" "$log_offset" "$log_file_b64" >"$temporary_state_file"
fi
mv -f -- "$temporary_state_file" "$refresh_state_file"
temporary_state_file=""

if [[ $refresh_mode == turns ]]; then
  echo "turns=$turn_counter/$turn_threshold trigger=turns refresh=$refresh_required$state_status"
else
  echo "turns=$turn_counter/$turn_threshold tokens=$token_counter/$token_threshold trigger=tokens refresh=$refresh_required$state_status"
fi
