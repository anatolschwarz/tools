# coedit — co-edit remote-run scripts live, from git

`coedit.sh` keeps a git-tracked file in sync with a live copy that runs elsewhere,
when the only local link to that live copy is a **staging file** written by some
remote-access tool. It is a byte-for-byte copier over a registry of bindings —
nothing more. No SSH, no EOL translation, no pushing.

## Topology

- The file lives under an **anchor root**: a git tree (`CodeRoot/work/<PROJECT>/` or
  `CodeRoot/tools/`) or the non-git scratch `CodeRoot/_zbale_/`. For git anchors this
  clone is the working tree — `commit` happens here (the **user** pushes). `_zbale_` is a
  non-git staging area: `import`/`export` work, but `commit` does not apply.
- The running copy is remote. Some access tool bridges it to a local **external**
  path: MobaXterm's `Downloads\MobaXterm\RemoteFiles\...` temp file (auto-scp's back
  on change while open), VS Code Remote-SSH, sshfs, WinSCP, scp/rsync, a network
  share — coedit does not care which. It only copies to/from the external path;
  getting that path to the remote is the access tool's job.
- Claude never touches the remote directly.

## Bindings

Step one is always establishing the connection between the anchor side and the
external staging side. coedit stores these bindings in `~/.coedit/bindings`
(tab-separated `name<TAB>external<TAB>anchor`) so paths live in the registry, not on
the command line. A binding is valid only when **exactly one side is under an anchor
root** (`work/`, `tools/`, or `_zbale_`) and the other is outside all of them — that
keeps one foot in a known tree and blocks arbitrary→arbitrary copies. `bind` figures
out which side is which; order doesn't matter.

Bindings are per-session in practice: the external staging path can change between
sessions (e.g. MobaX temp ids), so re-`bind` when the user gives new paths. The
registry design means such a change never alters the command line and so never
breaks an allow-list rule.

## Actions

```
coedit bind    <a> <b> [name]     register/replace a binding (name defaults to anchor basename)
coedit unbind  <name>
coedit list                       bindings + live state (in-sync / differ / external-missing)
coedit import  <name>             external -> anchor  (pull the edit made elsewhere into the anchor file)
coedit export  <name>             anchor -> external  (push my edit out; the access tool uploads it)
coedit compare <name>             in-sync? else show the diff  (external=<  anchor=>)
coedit commit  <name> <msg>       git add+commit the anchor side — git anchors only, NEVER pushes
coedit show    <name> [ext|anchor] print one side (default anchor)
```

Names match exactly, else by unique case-insensitive substring.

`import`/`export`/`compare`/`show` are **not** git operations — don't describe them
in git terms. `import` = the user's edit coming in; `export` = my edit going out.
`commit` is the only git operation, and only for git anchors; on a `_zbale_` binding
it refuses.

## Single-approval design

Every action fronts through this one script, so a single allow-list rule

```
Bash(bash /home/anatolschwartz/CodeRoot/tools/coedit/coedit.sh:*)
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
