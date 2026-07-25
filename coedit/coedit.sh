#!/usr/bin/env bash
# coedit — co-edit dispatcher over a registry of external<->anchor bindings.
#
# For editing a file that lives under an ANCHOR root (the git trees work/ or tools/,
# or the non-git scratch _zbale_) while a live copy is edited elsewhere and staged
# locally by SOME remote-access tool — MobaXterm, VS Code Remote-SSH, sshfs, WinSCP,
# scp/rsync, a network share, etc. coedit does not care which tool staged the external
# copy; it only requires that exactly one side of a binding is under an anchor root
# and the other is not.
#
# One command fronts every action, so a single allow-list rule
#   Bash(bash /mnt/c/Users/anatol.schwartz/ClaudeRoot/tools/coedit/coedit.sh:*)
# would make the whole workflow prompt-free. Paths live in the registry, not on
# the command line, so a staging path that changes between sessions never breaks
# that rule. (Adding the rule is the user's call — this script never touches settings.)
#
# Actions:
#   bind    <a> <b> [name]     register/replace a binding (one side under an anchor root,
#                              the other external; order-independent; name defaults to
#                              the anchor-side basename)
#   unbind  <name>             remove a binding
#   list                       show bindings + live sync state
#   import  <name>             external -> anchor  (the edit made elsewhere, into the anchor file)
#   export  <name>             anchor -> external  (my edit out; the access tool then uploads it)
#   compare <name>             report whether the two sides match, else the diff
#   commit  <name> <message>   git add+commit the anchor side (git anchors only; never pushes)
#   show    <name> [ext|anchor]  print one side (default anchor)
#
# Copies are byte-for-byte (no EOL processing). A binding is valid only if exactly
# one side is under an anchor root (below) and the other is outside all of them.
# Name lookup is exact, else a unique case-insensitive substring match.

set -euo pipefail

GIT_ROOTS=(
  "/mnt/c/Users/anatol.schwartz/ClaudeRoot/work"
  "/mnt/c/Users/anatol.schwartz/ClaudeRoot/tools"
)
# anchor roots = git roots + non-git scratch anchors. import/export/compare work on
# any anchor; commit is gated to git roots only.
ANCHOR_ROOTS=(
  "${GIT_ROOTS[@]}"
  "/mnt/c/Users/anatol.schwartz/ClaudeRoot/_zbale_"
)
REG="${HOME}/.coedit/bindings"        # name<TAB>external<TAB>anchor per line

mkdir -p "$(dirname "$REG")"; : >> "$REG"

die() { echo "coedit: $*" >&2; exit 1; }

is_git()    { local p=$1 r; for r in "${GIT_ROOTS[@]}";    do [[ $p == "$r"/* ]] && return 0; done; return 1; }
is_anchor() { local p=$1 r; for r in "${ANCHOR_ROOTS[@]}"; do [[ $p == "$r"/* ]] && return 0; done; return 1; }

# echo the registry line ("name<TAB>ext<TAB>anchor") for a name; exact, else unique substring
lookup() {
  local q=$1 line
  line=$(awk -F'\t' -v n="$q" '$1==n' "$REG")
  if [[ -n $line ]]; then printf '%s\n' "$line"; return 0; fi
  line=$(awk -F'\t' -v n="${q,,}" 'index(tolower($1), n) > 0' "$REG")
  local c; c=$(printf '%s' "$line" | grep -c . || true)
  (( c == 1 )) || die "name '$q' matches $c bindings (see: coedit list)"
  printf '%s\n' "$line"
}

copy() {  # src dst, byte-for-byte
  cp -f -- "$1" "$2"
  echo "coedit: copied $(wc -c <"$1") bytes"
  echo "  from $1"
  echo "  to   $2"
}

usage() { sed -n '2,/^set /{/^set /d;s/^# \?//p}' "$0"; }

action=${1:-}; [[ $# -gt 0 ]] && shift || true
case "$action" in
  bind)
    [[ $# -ge 2 ]] || die "usage: coedit bind <a> <b> [name]  (one side under an anchor root: work/, tools/, or _zbale_)"
    a=$(realpath -m -- "$1"); b=$(realpath -m -- "$2")
    if   is_anchor "$a" && ! is_anchor "$b"; then an=$a; e=$b
    elif is_anchor "$b" && ! is_anchor "$a"; then an=$b; e=$a
    else die "invalid pair: exactly one side must be under an anchor root (work/, tools/, or _zbale_), the other outside
  $a
  $b"
    fi
    name=${3:-$(basename -- "$an")}
    [[ $name == *$'\t'* ]] && die "name cannot contain a tab"
    tmp=$(mktemp)
    awk -F'\t' -v n="$name" '$1!=n' "$REG" > "$tmp"
    printf '%s\t%s\t%s\n' "$name" "$e" "$an" >> "$tmp"
    mv -f "$tmp" "$REG"
    echo "coedit: bound '$name'"; echo "  external $e"; echo "  anchor   $an"
    ;;
  unbind)
    [[ $# -ge 1 ]] || die "usage: coedit unbind <name>"
    name=$(lookup "$1" | cut -f1)
    tmp=$(mktemp); awk -F'\t' -v n="$name" '$1!=n' "$REG" > "$tmp"; mv -f "$tmp" "$REG"
    echo "coedit: unbound '$name'"
    ;;
  list)
    [[ -s $REG ]] || { echo "coedit: no bindings"; exit 0; }
    while IFS=$'\t' read -r name e g; do
      [[ -z ${name:-} ]] && continue
      if   [[ ! -f $e ]];                    then st="external-missing"
      elif cmp -s -- "$e" "$g" 2>/dev/null;  then st="in-sync"
      else st="differ"; fi
      printf '%s  [%s]\n  external %s\n  anchor   %s\n' "$name" "$st" "$e" "$g"
    done < "$REG"
    ;;
  import)  [[ $# -ge 1 ]] || die "usage: coedit import <name>";  line=$(lookup "$1"); copy "$(cut -f2 <<<"$line")" "$(cut -f3 <<<"$line")" ;;
  export)  [[ $# -ge 1 ]] || die "usage: coedit export <name>";  line=$(lookup "$1"); copy "$(cut -f3 <<<"$line")" "$(cut -f2 <<<"$line")" ;;
  compare)
    [[ $# -ge 1 ]] || die "usage: coedit compare <name>"
    line=$(lookup "$1"); e=$(cut -f2 <<<"$line"); g=$(cut -f3 <<<"$line")
    [[ -f $e ]] || die "external side missing: $e"
    if cmp -s -- "$e" "$g"; then echo "coedit: in sync ($(wc -c <"$g") bytes)"
    else echo "coedit: DIFFER (external=$(wc -c <"$e") anchor=$(wc -c <"$g") bytes)  [external=<  anchor=>]"; diff -- "$e" "$g" || true; fi
    ;;
  commit)
    [[ $# -ge 2 ]] || die "usage: coedit commit <name> <message>"
    name=$1; shift; msg="$*"
    g=$(lookup "$name" | cut -f3)
    is_git "$g" || die "commit applies only to git-tracked bindings; anchor is not under work/ or tools/: $g"
    d=$(dirname "$g")
    git -C "$d" add -- "$g"
    git -C "$d" commit -m "$msg" -- "$g"
    ;;
  show)
    [[ $# -ge 1 ]] || die "usage: coedit show <name> [ext|anchor]"
    line=$(lookup "$1"); side=${2:-anchor}
    case "$side" in ext|external) f=$(cut -f2 <<<"$line");; git|anchor|a) f=$(cut -f3 <<<"$line");; *) die "side must be ext|anchor";; esac
    cat -- "$f"
    ;;
  ""|-h|--help|help) usage ;;
  *) die "unknown action '$action' (try: coedit help)" ;;
esac
