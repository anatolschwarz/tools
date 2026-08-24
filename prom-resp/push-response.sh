#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=prom-resp-common.sh
source "$script_dir/prom-resp-common.sh"

usage() {
  echo "Usage: push-response.sh <session-token> [project] --response <path> --diff <path> [--remove-source]" >&2
  exit 1
}

(( $# >= 1 )) || usage

token_arg="$1"
shift
project_arg=""

if (( $# )) && [[ "$1" != --* ]]; then
  project_arg="$1"
  shift
fi

response_arg=""
diff_arg=""
remove_source=false

while (( $# )); do
  case "$1" in
    --response)
      (( $# >= 2 )) || usage
      [[ -z "$response_arg" ]] || usage
      response_arg="$2"
      shift 2
      ;;
    --diff)
      (( $# >= 2 )) || usage
      [[ -z "$diff_arg" ]] || usage
      diff_arg="$2"
      shift 2
      ;;
    --remove-source)
      $remove_source && usage
      remove_source=true
      shift
      ;;
    *)
      usage
      ;;
  esac
done

[[ -n "$response_arg" && -n "$diff_arg" ]] || usage

prom_resp_set_identity "$token_arg" "$project_arg"

caller_dir="$(pwd -P)"
source_root="$(git -C "$caller_dir" rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$source_root" && "$source_root" != "/" ]] || {
  echo "Run push-response.sh from inside the calling project's Git working tree" >&2
  exit 1
}
source_root="$(cd -- "$source_root" && pwd -P)"
source_git_dir="$(git -C "$source_root" rev-parse --absolute-git-dir)"
source_git_dir="$(cd -- "$source_git_dir" && pwd -P)"

response_source="$(prom_resp_resolve_source "Response source" "$response_arg" "$token-response.md" "$source_root")"
diff_source="$(prom_resp_resolve_source "Diff source" "$diff_arg" "$token-diff.patch" "$source_root")"

for source in "$response_source" "$diff_source"; do
  case "$source" in
    "$source_git_dir"/*)
      echo "Artifact source must not be inside the calling project's Git directory: $source" >&2
      exit 1
      ;;
  esac
done

prom_resp_resolve_repo "$script_dir"

cd "$repo"

branch="$(git branch --show-current)"
[[ "$branch" == "main" ]] || {
  echo "Handoff repository must be on branch main, not: ${branch:-detached HEAD}" >&2
  exit 1
}

case "$response_source" in
  "$repo"/*)
    echo "Response source must be outside the handoff repository: $response_source" >&2
    exit 1
    ;;
esac
case "$diff_source" in
  "$repo"/*)
    echo "Diff source must be outside the handoff repository: $diff_source" >&2
    exit 1
    ;;
esac

unrelated_staged=()
while IFS= read -r -d '' file; do
  if [[ "$file" != "$response_file" && "$file" != "$diff_file" ]]; then
    unrelated_staged+=("$file")
  fi
done < <(git diff --cached --name-only -z)

if (( ${#unrelated_staged[@]} )); then
  echo "Refusing to commit unrelated staged files:" >&2
  printf '  %s\n' "${unrelated_staged[@]}" >&2
  exit 1
fi

if [[ -n "$project" ]]; then
  project_dir="$repo/$project"

  [[ ! -L "$project_dir" ]] || {
    echo "Project path must not be a symbolic link: $project_dir" >&2
    exit 1
  }
  [[ ! -e "$project_dir" || -d "$project_dir" ]] || {
    echo "Project path exists and is not a directory: $project_dir" >&2
    exit 1
  }

  mkdir -p -- "$project_dir"
fi

for file in "$response_file" "$diff_file"; do
  [[ ! -L "$file" ]] || {
    echo "Artifact destination must not be a symbolic link: $repo/$file" >&2
    exit 1
  }
done

cp -- "$response_source" "$response_file"
cp -- "$diff_source" "$diff_file"

git add -- "$response_file" "$diff_file"

if ! git diff --cached --quiet -- "$response_file" "$diff_file"; then
  git commit -m "Add response $commit_target"
fi

git pull --rebase origin main
git push origin main

if $remove_source; then
  rm -- "$response_source" "$diff_source"
fi
