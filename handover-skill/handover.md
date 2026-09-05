# /handover
Use to preserve only what materially matters from the current session for the next one.

## Grounding

Use only evidence available in the current environment: conversation history, project/workspace files, repositories, tools, task state, and tool output.

Do not invent missing state. Clearly label any inference as inferred.

## When triggered

1. Review what actually happened this session.
   - Check completed, in-flight, blocked, or abandoned work.
   - If repository access exists, inspect relevant commits and uncommitted changes.

2. Preserve only what the next session needs:
   - decisions
   - constraints
   - completed work
   - unfinished work
   - important footguns or broken assumptions
   - unresolved questions

3. Filter aggressively.
   - Ignore routine execution noise.
   - Do not write a chronological session log.

4. Persistent notes:
   - Inside a project/workspace, update existing persistent notes only with information future sessions need.
   - Preserve their structure.
   - Outside a project/workspace, use only the current conversation/session.
   - Do not create a new notes system.

5. If uncommitted changes appear worth committing, ask before committing.

6. Do not claim work was shipped, committed, deployed, completed, or changed unless verified.

## Output

### What shipped this session
Verified completed work, including commits or deploys when known.

### What's still in flight
Incomplete work with enough context to continue.

### Watch-outs
Important gotchas, constraints, broken assumptions, or surprising state.

### Open questions for me
Only questions that require the user's decision or information.

If a section has nothing worth preserving, write `None`.

## CLI agent add-on

When direct repository, filesystem, or task-state access is available:

- Run `git status`.
- Inspect relevant uncommitted diffs.
- Inspect commits made during the session when the session start point is known and verifiable.
- Inspect available task/todo state.
- Verify relevant files and artifacts directly rather than relying only on conversation history.

