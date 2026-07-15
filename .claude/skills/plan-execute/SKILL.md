---
name: plan-execute
description: >
  Execute a plans/PLAN-*.md file produced by the plan-delegate skill:
  spawn one subagent per task with the model and effort the plan assigns,
  respect phase order, dependencies and [P] parallel markers, verify each
  task's acceptance criteria, and update the plan file with progress. Use
  when the user says "execute the plan", "run the plan", "start phase N",
  "/plan-execute", or points at a PLAN-*.md file to be carried out.
---

# Plan Execute

You are the **orchestrator**. The plan file contains all decisions; your job
is dispatch, verification, and bookkeeping — not re-planning and not doing
the tasks yourself. Subagents do the work on the models the plan paid for.

## Step 0 — Load and gate the plan

1. Locate the plan: the file the user named, else the newest
   `plans/PLAN-*.md` in the repo. Read it fully once — it is your single
   source of truth for the rest of the session.
2. **Gate on "Open questions":** if that section is non-empty, STOP and ask
   the user (AskUserQuestion) before spawning anything — executing around an
   open question produces work that gets thrown away.
3. Restate the "Assumptions" list in one short message so the user can veto
   cheaply, then proceed (do not block on assumptions, only on questions).
4. Create one harness task per plan task (TaskCreate) so progress is visible;
   mirror dependencies with blockedBy.

## Step 1 — Map each task's model and effort to a subagent

Model mapping (plan name → Agent tool `model` parameter):

| Plan says | Spawn with |
|---|---|
| Haiku 4.5 | `model: "haiku"` |
| Sonnet 5 | `model: "sonnet"` |
| Opus 4.8 | `model: "opus"` |
| Fable 5 | `model: "fable"` |

Agent type: `general-purpose` for tasks that write code/files; `Explore` for
read-only investigation tasks (it cannot edit). If the repo defines a custom
agent in `.claude/agents/` whose model **and** reasoning effort match the
task's assignment, prefer it — agent definitions are the only place effort
is set mechanically.

Effort handling when no matching agent definition exists: the Agent tool has
no effort parameter, so encode the plan's effort behaviorally in the prompt:

- `low` → "Do exactly what is specified, minimal exploration, no extras,
  terse report."
- `high` (default) → no extra instruction.
- `xhigh`/`max` → "Take the time to explore alternatives and verify your
  work end-to-end before reporting."

## Step 2 — Build each subagent prompt

Subagents start with ZERO context. Each prompt must contain, copied or
adapted from the plan file — never abbreviated from memory:

1. The task's **Context, Inputs, Work, Output, Acceptance** sections
   verbatim.
2. Repo grounding: working directory, branch to work on, and the one line
   "Read CLAUDE.md first."
3. Results from dependency tasks *that the task needs* — summarized to the
   facts required (file paths created, decisions made), not full transcripts.
4. The reporting contract: "End with: what you produced (exact paths), the
   acceptance-criteria commands you ran and their output, and anything you
   could not do. Do not summarize the plan back."
5. The effort line from Step 1.

## Step 3 — Dispatch in plan order

- Execute **phase by phase**; never start phase N+1 while phase N tasks are
  incomplete unless the plan marks them independent.
- Within a phase, spawn all `[P]` tasks **in one message** (parallel,
  background); run sequential tasks one at a time in dependency order.
- Update the harness task to in_progress on spawn, completed on verified
  completion.
- For a follow-up or fix on a task an agent already did, **SendMessage the
  same agent** (it keeps its context) instead of spawning a fresh one — a
  respawn re-pays the entire context load.

## Step 4 — Verify before accepting

A subagent's "done" is a claim, not a fact. For each finished task, check
the plan's acceptance criteria yourself: run the stated command, or confirm
the artifact exists and is non-trivial. Only then mark complete.

Failure policy, in order:

1. **One retry with context**: SendMessage the same agent with the concrete
   failure (error output, which criterion failed).
2. **One escalation**: if it fails again, respawn the task once on the next
   model tier up (haiku→sonnet→opus→fable), including both failure reports.
3. **Stop the affected chain**: if the escalated attempt fails, mark the
   task blocked, skip only its dependents, keep independent tasks running,
   and report to the user. Never burn a third attempt silently.

## Step 5 — Bookkeeping and final report

- After each task completes, update the plan file: append
  `✅ done <date>` (or `❌ blocked: <reason>`) to the task heading. Commit
  plan-file updates with the work.
- When all phases end (or execution stops), report: tasks completed /
  blocked per phase, artifacts produced (paths), model usage vs. plan
  (note any escalations — feedback for the next plan-delegate run), and
  what remains. Then run the session-closer skill if work touched git.

## Orchestrator token rules

- You read the plan file ONCE; subagents get excerpts, not the whole file.
- Never open the files subagents created just to admire them — verify via
  acceptance commands; read only what verification requires.
- Keep dependency handoffs to facts (paths, names, decisions) — never paste
  one agent's full report into another's prompt.
- Do not narrate between spawns; your visible output is the phase updates
  and the final report.
