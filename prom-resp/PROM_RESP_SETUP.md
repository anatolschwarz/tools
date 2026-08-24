# ChatGPT ↔ Codex Handoff Setup

## Components

- Maintained tool: `/home/anatolschwartz/CodeRoot/tools/prom-resp`
- Local handoff repository: `/home/anatolschwartz/CodeRoot/prom-resp-handoff`
- Handoff remote: `git@github-prom-resp:anatolschwartz/prom-resp.git`

The calling Codex session generates response and diff artifacts in its own Git
project or under `/tmp`. It passes those source paths to the maintained tool.
The tool resolves and writes the handoff repository internally, so neither the
calling project nor the orchestrator needs its local path or Git details.

## Tool configuration

Configure the handoff repository in the `tools` repository's local Git config:

```bash
git -C /home/anatolschwartz/CodeRoot/tools config --local \
  prom-resp.handoffDir /home/anatolschwartz/CodeRoot/prom-resp-handoff
```

`PROM_RESP_HANDOFF_DIR` may override this setting for testing. The configured
path must be an existing Git working-tree root on branch `main`.

The handoff repository uses the dedicated SSH host `github-prom-resp` and its
write-enabled deploy key. Never store or copy the private key into a repository.

## Source artifacts

Run the tool from inside the calling project's Git working tree. Both source
files must be regular, non-symbolic-link files located inside that project or
under `/tmp`, but not inside the project's Git administrative directory.

Their basenames must be:

```text
<session-token>-response.md
<session-token>-diff.patch
```

Use a temporary directory outside the calling Git worktree by default. This
prevents the handoff artifacts from appearing in the source diff. If a
project-local directory is used instead, it must be excluded from the generated
diff and from source-project commits.

The response file contains the exact final response. The operational prompt
must explicitly define what the diff represents, such as the current working
tree, staged checkpoint, or a specific commit.

## Invocation

Without a project, artifacts are published at the handoff repository root:

```bash
/home/anatolschwartz/CodeRoot/tools/prom-resp/push-response.sh \
  <session-token> \
  --response <source-response-path> \
  --diff <source-diff-path>
```

With a project, artifacts are published under `<project>/`:

```bash
/home/anatolschwartz/CodeRoot/tools/prom-resp/push-response.sh \
  <session-token> <project> \
  --response <source-response-path> \
  --diff <source-diff-path>
```

Add `--remove-source` to delete both source files only after the Git push
succeeds. Without it, the source files remain in place.

The tool creates the project directory when needed, copies both artifacts to
their canonical destination names, refuses unrelated staged handoff files,
commits changed artifacts, pulls/rebases `origin main`, and pushes `main`.

## Handoff repository layout

Legacy/no-project invocation:

```text
<handoff-repository>/
  <session-token>-response.md
  <session-token>-diff.patch
```

Project-scoped invocation:

```text
<handoff-repository>/
  <project>/
    <session-token>-response.md
    <session-token>-diff.patch
```

## Future orchestrator prompt contract

Future operational prompts should provide:

- the fixed session token;
- the project identifier, when project-scoped layout is required;
- the required response contents;
- the exact source of the diff;
- local source paths outside the diff being generated;
- the maintained `push-response.sh` invocation.

They must not expose or instruct Codex to write into the internal handoff
repository. A normal project-scoped handoff instruction is:

```text
Session token: <session-token>
Handoff project: <project>
Diff artifact: <explicit working-tree, staged, or commit diff requirement>

After implementation and validation:
1. Create /tmp/prom-resp/<session-token>/.
2. Write the exact final response to
   /tmp/prom-resp/<session-token>/<session-token>-response.md.
3. Generate the required diff at
   /tmp/prom-resp/<session-token>/<session-token>-diff.patch.
4. Run exactly:
   /home/anatolschwartz/CodeRoot/tools/prom-resp/push-response.sh \
     <session-token> <project> \
     --response /tmp/prom-resp/<session-token>/<session-token>-response.md \
     --diff /tmp/prom-resp/<session-token>/<session-token>-diff.patch \
     --remove-source
5. Claim handoff success only after the push succeeds, then print the same final
   response normally.
```

`docs/CODEX_PROMPTS.md` in calling projects is a historical prompt archive.
Existing prompt bodies and their obsolete commands remain unchanged as evidence;
they are not current operating instructions.

## Codex permissions

Calling projects use their normal `workspace-write` sandbox. The handoff
repository must not be added as a writable root because Codex writes only the
local source artifacts.

The approved command rule should allow only the maintained executable:

```text
/home/anatolschwartz/CodeRoot/tools/prom-resp/push-response.sh
```

That command performs the protected handoff-repository Git and network
operations. Restart Codex after changing project configuration or user command
rules.

## Deferred provider setup documentation

Research and document the current official setup requirements before treating
provider integration documentation as complete:

- GitHub repository, deploy-key, access, and branch settings required for the
  publishing side;
- ChatGPT GitHub connection, repository selection, and required permissions;
- Claude.ai GitHub connection, repository selection, and required permissions;
- equivalent setup for any other handoff consumer;
- least-privilege guidance for private repositories;
- verification and troubleshooting steps for each provider.

Verify these requirements against each provider's current official
documentation when this work is resumed. Do not fill them in from memory.
