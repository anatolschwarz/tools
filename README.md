# tools

Private collection of reusable media / encoding support tools. One
self-contained directory per tool.

| Tool | Purpose |
|------|---------|
| [syncnet-lipsync](syncnet-lipsync/) | Measure the baked-in A/V sync offset of a media file (vendored SyncNet + `sync_offset.py` CLI). |
| [coedit](coedit/) | Co-edit a remote-run script — bind the remote-staged copy to its versioned copy, then import / export / compare / commit. |

Large model weights are **not** tracked — fetch them per each tool's install
guide (e.g. `sh download_model.sh`).
