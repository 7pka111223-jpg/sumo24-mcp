---
name: session-closer
description: >
  End-of-session landing checklist: make sure the session's work actually
  lands (merged, PR'd and watched, or explicitly abandoned) instead of
  stranding on a forgotten branch. Use whenever the user says "wrap up",
  "close the session", "we're done", "land this", or when a session that
  created commits or branches is about to end for any reason. Also use after
  a PR is merged, to clean up.
---

# Session Closer

Work that stays on an unmerged branch after the session ends is usually lost:
the next session re-derives the context, or the work is redone from scratch.
This checklist prevents that. Run it before ending any session that touched
git.

## Step 1 — Inventory what this session produced

```
git status --short          # uncommitted work?
git log origin/<default>..HEAD --oneline   # unpushed / unmerged commits
git branch -r | grep claude # session branches on the remote
```

Also list: PRs opened this session, files created outside git (reports,
scratch outputs the user may want), and configuration changed (settings,
Routines, connectors).

## Step 2 — Land every commit, one of three ways

For each branch/commit set, pick exactly one — never leave a fourth state
("it's on the branch somewhere"):

1. **Merge now** — for work the user approved and that is verified (tests
   pass / manually exercised). Merge to the default branch and push. Prefer
   this for small, finished work; open PRs in this workflow historically go
   stale.
2. **PR + watch** — for work that needs review or CI. Open the PR, then call
   `subscribe_pr_activity` so this session (or its successor) babysits it to
   merged — a PR nobody watches is a slow abandon.
3. **Explicit abandon** — if the work is experimental or superseded, say so
   out loud, and ask the user whether to delete the branch. Never silently
   walk away from a branch.

Uncommitted changes: commit them (even as WIP with a clear message) or
explicitly discard with the user's confirmation. Never end a session with a
dirty tree.

## Step 3 — Update the repo's memory

- If the session established a convention, gotcha, command, or decision that
  a future session would otherwise re-discover, add 1-3 lines to CLAUDE.md
  (create it via `/init` if missing). Do not dump a changelog — only durable
  facts a future session needs.
- If the session created a skill or changed `.claude/` config, confirm it is
  committed and pushed (skills only work when they reach the default branch).

## Step 4 — Clean up

- Delete remote branches that are fully merged or duplicated
  (`git push origin --delete <branch>`). If the environment's git proxy
  blocks deletion (HTTP 403), tell the user which branches to delete in the
  GitHub UI instead — list them explicitly.
- Remove scratch files accidentally committed; keep deliverables.

## Step 5 — Closing report

End with a short report in this order:

1. **Landed**: what merged/PR'd, with links.
2. **Watching**: PRs under subscription and what happens next.
3. **Abandoned**: what was dropped and why.
4. **Needs you**: any action only the user can do (UI-only settings,
   branch deletions blocked by the proxy, pending approvals) — each as one
   imperative sentence.

If all four sections would be empty, say "nothing to land" and stop.
