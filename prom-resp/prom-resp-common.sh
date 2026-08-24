prom_resp_validate_component() {
  local label="$1"
  local value="$2"

  [[ -n "$value" &&
    "$value" != "." &&
    "$value" != ".." &&
    "$value" != */* &&
    "$value" != *$'\n'* &&
    "$value" != *$'\r'* ]] || {
    echo "$label must be a nonempty single path component: $value" >&2
    exit 1
  }
}

prom_resp_set_identity() {
  token="$1"
  project="${2:-}"
  prom_resp_validate_component "Session token" "$token"

  if [[ -n "$project" ]]; then
    prom_resp_validate_component "Project" "$project"
    [[ "$project" != ".git" ]] || {
      echo "Project must not name the Git administrative directory: $project" >&2
      exit 1
    }
    artifact_prefix="$project/"
  else
    artifact_prefix=""
  fi

  response_file="${artifact_prefix}${token}-response.md"
  diff_file="${artifact_prefix}${token}-diff.patch"
  commit_target="${artifact_prefix}${token}"
}

prom_resp_resolve_repo() {
  local script_dir="$1"
  local handoff_dir="${PROM_RESP_HANDOFF_DIR:-}"
  local git_root

  if [[ -z "$handoff_dir" ]]; then
    handoff_dir="$(git -C "$script_dir" config --local --get prom-resp.handoffDir 2>/dev/null || true)"
  fi

  [[ -n "$handoff_dir" ]] || {
    echo "Missing handoff repository setting: prom-resp.handoffDir" >&2
    exit 1
  }

  [[ "$handoff_dir" == /* ]] || {
    echo "Handoff repository path must be absolute: $handoff_dir" >&2
    exit 1
  }

  [[ -d "$handoff_dir" ]] || {
    echo "Handoff repository directory does not exist: $handoff_dir" >&2
    exit 1
  }

  repo="$(cd -- "$handoff_dir" && pwd -P)"
  git_root="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null || true)"

  [[ -n "$git_root" ]] || {
    echo "Handoff repository path is not in a Git working tree: $repo" >&2
    exit 1
  }

  git_root="$(cd -- "$git_root" && pwd -P)"
  [[ "$repo" == "$git_root" ]] || {
    echo "Handoff repository path is not the Git working-tree root: $repo" >&2
    exit 1
  }
}

prom_resp_resolve_source() {
  local label="$1"
  local source_path="$2"
  local expected_name="$3"
  local source_root="$4"
  local resolved

  [[ ! -L "$source_path" && -f "$source_path" ]] || {
    echo "$label must be an existing regular, non-symbolic-link file: $source_path" >&2
    exit 1
  }

  resolved="$(realpath -e -- "$source_path")"
  [[ "${resolved##*/}" == "$expected_name" ]] || {
    echo "$label filename must be $expected_name: $resolved" >&2
    exit 1
  }

  case "$resolved" in
    "$source_root"/* | /tmp/*) ;;
    *)
      echo "$label must be inside the calling Git project or /tmp: $resolved" >&2
      exit 1
      ;;
  esac

  printf '%s\n' "$resolved"
}
