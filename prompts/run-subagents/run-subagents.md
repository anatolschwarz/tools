* **Run-subagents:**

  * Default to sub-agents for:

    * broad codebase/repository scans
    * large research tasks
    * multi-file reviews
    * test/validation sweeps
    * repetitive inspection across many items
    * independent comparison/evaluation tasks
    * work likely to produce large raw output
  * Split work into independent units; give each sub-agent a self-contained brief and required output format.
  * Sub-agents return summaries ≤30 lines, including findings, evidence references, and unresolved issues; no raw content or logs.
  * Keep raw inspection output in sub-agent contexts; retain requirements, decisions, plan, status, and summaries in the parent.
  * Parallelize independent work where possible.
  * Report substantive sub-agent failures instead of silently taking over their work.
