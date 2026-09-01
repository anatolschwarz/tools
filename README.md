# tools

Private collection of reusable tools. One self-contained directory per tool.

| Tool | Purpose |
|------|---------|
| [instruction-refresh](instruction-refresh/) | Track turn/token thresholds and reload agent instructions when required. |
| [syncnet-lipsync](syncnet-lipsync/) | Measure the baked-in A/V sync offset of a media file (vendored SyncNet + `sync_offset.py` CLI). |
| [coedit](coedit/) | Co-edit a remote-run script — bind the remote-staged copy to its versioned copy, then import / export / compare / commit. |
| [prom-resp](prom-resp/) | Publish response and diff artifacts to the dedicated GitHub handoff repository. |

Large model weights are **not** tracked — fetch them per each tool's install
guide (e.g. `sh download_model.sh`).
