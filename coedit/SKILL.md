---
name: coedit
description: Synchronize files between a CodeRoot anchor and an external remote-access staging file through the local coedit binding registry. Use for binding, listing, comparing, importing, exporting, showing, or committing coedit-managed files, and for co-editing remote-run files through a staged local copy.
---

# Coedit

Use the fixed dispatcher:

```bash
bash /home/anatolschwartz/CodeRoot/tools/coedit/coedit.sh <action> [arguments]
```

Run the requested action directly when its inputs are known. Use `list` to discover
bindings and live state. Use `compare` when asked what differs or when the copy
direction is unclear.

Preserve these meanings:

- `bind`: register one external path and one CodeRoot anchor path.
- `import`: copy external to anchor; the user's edit comes in.
- `export`: copy anchor to external; the agent's edit goes out.
- `compare` and `show`: inspect files; they are not Git operations.
- `commit`: commit only the anchor file, only under a Git anchor, and never push.

Do not access the remote directly. Do not infer an overwrite direction when it is
unclear; compare first, then ask one focused question if needed.

Use the exact dispatcher path so client-specific scoped permission rules can match
it. Permission setup remains the user's and client's responsibility.

When changing coedit itself, consult `README.md`.
