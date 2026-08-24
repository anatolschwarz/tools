# ChatGPT ↔ Codex Handoff Setup

## Components

- Maintained tool: `/home/anatolschwartz/CodeRoot/tools/prom-resp`
- Local handoff repository: `/home/anatolschwartz/CodeRoot/prom-resp-handoff`
- Handoff remote: `git@github-prom-resp:anatolschwarz/prom-resp-handoff.git`

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

## GitHub publisher setup

Keep the handoff repository private unless its response and diff artifacts are
deliberately public. Use `main` as its default branch. The maintained tool
requires its configured local handoff working tree to be on `main` and pushes
`origin main` directly.

Create a dedicated SSH key pair for this handoff repository. In the repository
on GitHub, open **Settings → Deploy keys → Add deploy key**, add only the public
key, and select **Allow write access**. A deploy key is scoped to one repository
and is read-only unless write access is explicitly enabled. Keep the private key
outside every repository and configure the `github-prom-resp` SSH host alias to
use it.

Review branch protections and rulesets targeting `main`. They must permit the
publisher's direct pushes; do not weaken unrelated repository protections.

Official GitHub references:

- [Managing deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
- [Testing an SSH connection](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/testing-your-ssh-connection)
- [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)

### Publisher verification

Test the configured SSH alias:

```bash
ssh -T git@github-prom-resp
```

GitHub's successful authentication message says that it does not provide shell
access, and this test normally exits with status 1. Then verify repository read
access without changing it:

```bash
git -C /home/anatolschwartz/CodeRoot/prom-resp-handoff ls-remote origin main
```

The definitive write test is a real `push-response.sh` handoff with a unique
test session token. Treat the publisher as verified only after the command
pushes successfully and both canonical artifacts appear on remote `main`.

### Publisher troubleshooting

- `Permission denied (publickey)`: run
  `ssh -vT git@github-prom-resp`; confirm that the alias resolves to GitHub,
  uses the `git` SSH user, and offers the dedicated private key. Confirm that
  the matching public key remains installed on the handoff repository.
- Read succeeds but push fails: confirm **Allow write access** is enabled for
  the deploy key and inspect the rules applying to `main`.
- Wrong repository or account: compare `git remote -v` with the configured
  `anatolschwarz/prom-resp-handoff` remote before changing any credentials.

## ChatGPT consumer setup

The ChatGPT GitHub app is a read-only consumer: it can search and analyze
repository content but cannot push code, updates, or pull requests.

1. In ChatGPT, open **Settings → Apps** and select **GitHub**.
2. Connect the app and complete GitHub authorization.
3. On GitHub's repository-access page, choose selected repositories and grant
   access to `anatolschwarz/prom-resp-handoff` only.
4. If ChatGPT separately asks which repositories to sync, select the handoff
   repository there as well. Sync selection improves retrieval but is separate
   from GitHub repository authorization.

Availability varies by ChatGPT plan and product surface. The official setup
page does not enumerate the app's underlying GitHub permission scopes; review
the permissions shown by GitHub during authorization and do not accept
unexpected write access.

Official references:

- [Connecting GitHub to ChatGPT](https://help.openai.com/en/articles/11145903)
- [Installing a third-party GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party)

### Consumer verification

Publish a handoff whose response and diff contain different unique markers.
In ChatGPT, enable the GitHub app and ask it to retrieve each marker from the
expected project-scoped paths on `anatolschwarz/prom-resp-handoff`. Verify that
it identifies the response and diff artifacts separately and reports their
contents accurately. This verifies consumption; it does not authorize ChatGPT
to publish handoffs.

### Consumer troubleshooting

- Allow about five minutes after connecting or changing repository access.
- In **Settings → Apps → GitHub**, use **Choose repositories** or
  **Configure Repositories on GitHub** and confirm that the handoff repository
  is selected.
- If GitHub organization policy blocks the app, request approval from the
  repository or organization administrator.
- If the selected repository is still absent, search on GitHub for
  `repo:anatolschwarz/prom-resp-handoff import`, then allow 5–10 minutes for
  GitHub's search index to update.
- If the app is available in Deep Research or agent mode but not normal chat,
  check the current plan and product-surface availability.

## Least-privilege model

- Only the publisher side has write access, through the repository-scoped
  deploy key. Codex exposes that publisher path only through the approved
  `push-response.sh` command.
- ChatGPT receives read-only access through its GitHub app, limited to the
  handoff repository.
- Do not give ChatGPT the publisher's deploy key, a personal access token, the
  local handoff path, or access to calling source repositories.
- Do not select all private repositories when authorizing the consumer.
- Remove unused app access and deploy keys. If the publisher's private key is
  exposed, replace it and remove the compromised deploy key immediately.
