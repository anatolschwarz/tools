# coedit — co-edit remote-run scripts live, from git

`coedit.sh` keeps a git-tracked file in sync with a live copy that runs elsewhere,
when the only local link to that live copy is a **staging file** written by some
remote-access tool. It is a byte-for-byte copier over a registry of bindings —
nothing more. No SSH, no EOL translation, no pushing.

## Topology

- The file is git-tracked under `ClaudeRoot/work/<PROJECT>/` or `ClaudeRoot/tools/`.
  This clone is the working tree — every commit happens here (the **user** pushes).
- The running copy is remote. Some access tool bridges it to a local **external**
  path: MobaXterm's `Downloads\MobaXterm\RemoteFiles\...` temp file (auto-scp's back
  on change while open), VS Code Remote-SSH, sshfs, WinSCP, scp/rsync, a network
  share — coedit does not care which. It only copies to/from the external path;
  getting that path to the remote is the access tool's job.
- Claude never touches the remote directly.

## Bindings

Step one is always establishing the connection between the git side and the
external staging side. coedit stores these bindings in `~/.coedit/bindings`
(tab-separated `name<TAB>external<TAB>git`) so paths live in the registry, not on
the command line. A binding is valid only when **exactly one side is under a git
root** (`work/` or `tools/`) and the other is outside all of them — that keeps one
foot in the tracked tree and blocks arbitrary→arbitrary copies. `bind` figures out
which side is which; order doesn't matter.

Bindings are per-session in practice: the external staging path can change between
sessions (e.g. MobaX temp ids), so re-`bind` when the user gives new paths. The
registry design means such a change never alters the command line and so never
breaks an allow-list rule.

## Actions

```
coedit bind    <a> <b> [name]   register/replace a binding (name defaults to git basename)
coedit unbind  <name>
coedit list                     bindings + live state (in-sync / differ / external-missing)
coedit import  <name>           external -> git   (pull the edit made elsewhere into the tracked file)
coedit export  <name>           git -> external   (push my edit out; the access tool uploads it)
coedit compare <name>           in-sync? else show the diff  (external=<  git=>)
coedit commit  <name> <msg>     git add+commit the gitted side only — NEVER pushes
coedit show    <name> [ext|git] print one side (default git)
```

Names match exactly, else by unique case-insensitive substring.

`import`/`export`/`compare`/`show` are **not** git operations — don't describe them
in git terms. `import` = the user's edit coming in; `export` = my edit going out.

## Single-approval design

Every action fronts through this one script, so a single allow-list rule

```
Bash(bash /mnt/c/Users/anatol.schwartz/ClaudeRoot/tools/coedit/coedit.sh:*)
```

makes the whole workflow prompt-free. **Adding that rule is the user's decision** —
this script never edits `settings.local.json`.

## EOL

Copies are byte-for-byte; coedit does no EOL processing. The chain is LF end-to-end
(editors save LF on the Linux remote; Claude writes LF). A repo `.gitattributes`
forcing LF is only a commit-time backstop for a stray Windows-side checkout — dormant
in normal use.

## Not included

Auto reverse-detection (watching the external file and pulling on change) is
deliberately out. Sync is explicit via `import`/`export`.
