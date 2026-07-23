# tools/ — collaboration instructions

## Co-editing remote-run scripts (MobaX ⇄ git association)

The canonical spec lives in the sibling `work` repo: **`../work/CLAUDE.md`** (both repos sit
side by side under `ClaudeRoot/`). The same workflow applies here — do not duplicate it.

In short: git working tree = the local clone; MobaX's temp file (`Downloads\MobaXterm\...`) is
the only conduit to the remote; associate a file per session (gitted path + temp path re-told
each time), forward = edit git then copy to temp, reverse = Monitor temp hash → git. See
`../work/CLAUDE.md` for the full rules and guardrails.
