---
name: plan-delegate
description: >
  Assess a prompt or project request, break it into phases and fully-specified
  tasks, assign the cheapest capable Claude model to each task to minimize
  token spend, and write the result to a plans/PLAN-*.md file. Use whenever the
  user asks to "plan", "break down", "decompose", "delegate", "which model
  should do X", "optimize tokens for this project", or hands over any request
  large enough to need more than one work session. Also use BEFORE starting any
  multi-part build so the work is routed to the right models from the start.
---

# Plan & Delegate

Turn a raw request into an execution plan where every task is self-contained
(no hidden context, no assumptions) and every task names the cheapest Claude
model that can do it well. The deliverable is a markdown plan file — you do
NOT execute the tasks in the same session unless the user asks.

## Step 1 — Assess the prompt

Read the user's request and the repository (if one is in scope). Extract:

1. **Objective** — one sentence, in the user's own terms.
2. **Deliverables** — concrete artifacts (files, PRs, docs, deployed things).
3. **Constraints** — stated limits (offline-only, language, deadline, budget)
   AND repo conventions found in CLAUDE.md.
4. **Unknowns** — anything the prompt does not specify that changes the plan.
   Do NOT silently assume. Each unknown becomes either (a) a question listed
   in the plan's "Open questions" section, or (b) a stated assumption in the
   plan's "Assumptions" section with the reason a default was chosen.

If an unknown blocks even the shape of the plan, ask the user before writing
the file (AskUserQuestion when available). Otherwise write the plan and flag.

## Step 2 — Decompose into phases and tasks

- A **phase** is a sequential milestone; phase N+1 may depend on phase N.
  Typical arc: Investigate → Build → Verify → Ship/Document.
- A **task** is a unit one model can complete in one session without asking
  anything. Tasks inside a phase should be parallelizable where possible —
  mark them `[P]`.

**The self-containment rule (most important):** write every task description
so that an agent with ZERO conversation history could execute it. Each task
must state, in prose (not fragments):

- **Context**: why this task exists and how it fits the objective.
- **Inputs**: exact file paths, URLs, branch names, data locations.
- **Work**: what to do, spelled out — name functions/files to touch, name the
  approach if it was already decided, and say what NOT to do (scope fence).
- **Output**: the exact artifact (file path, PR, report section).
- **Acceptance criteria**: how the executor verifies it is done (command to
  run, expected behavior, checklist). Never "works correctly" — always a
  testable statement.
- **Depends on**: task IDs that must finish first, or "none".

If you cannot fill in Inputs or Acceptance criteria for a task, the task is
underspecified — move the gap to "Open questions" instead of hand-waving.

## Step 3 — Delegate a model per task

Route each task to the cheapest model that is genuinely capable of it.
Pricing and capabilities (verified 2026-07; per 1M tokens, input/output):

| Model | ID | $/1M in/out | Context | Use for |
|---|---|---|---|---|
| Haiku 4.5 | `claude-haiku-4-5` | $1 / $5 | 200K | Mechanical, well-specified work: renames, format conversion, boilerplate from a template, extracting/listing data, simple lookups, running defined test commands, classification |
| Sonnet 5 | `claude-sonnet-5` | $3 / $15 (intro $2/$10 to 2026-08-31) | 1M | Standard development: implementing a specified feature, writing tests, fixing a diagnosed bug, docs, refactors with clear scope. Near-Opus coding quality — the default workhorse |
| Opus 4.8 | `claude-opus-4-8` | $5 / $25 | 1M | Architecture and judgment: designing the approach, debugging undiagnosed failures, cross-cutting refactors, security-sensitive changes, code review, anything ambiguous |
| Fable 5 | `claude-fable-5` | $10 / $50 | 1M | Only the hardest long-horizon work: multi-hour autonomous runs, problems Opus attempted and failed, plans spanning many interacting systems. Never route routine tasks here |

Routing rules:

1. **Default to Sonnet 5** for implementation tasks; escalate to Opus 4.8 only
   when the task requires deciding *how*, not just *doing*.
2. **Batch Haiku work**: group several mechanical tasks into one Haiku session
   rather than many small sessions (each session re-pays context loading).
3. **One planner, cheap executors**: the phase that produces decisions runs on
   Opus/Fable once; downstream tasks consume those decisions on Sonnet/Haiku.
4. **Effort setting** (Claude Code / API `output_config.effort`): recommend
   `low` for Haiku-class tasks, `high` (default) for Sonnet/Opus work, `xhigh`
   only for the hardest coding/agentic tasks. Note it per task when it differs
   from `high`.
5. **In-session delegation**: when the plan will be executed inside Claude
   Code, note that read-only fan-out (searching, summarizing many files) goes
   to `Explore`/`general-purpose` subagents with `model: "haiku"` or
   `model: "sonnet"`, keeping the orchestrator's context small.
6. Flag any task where model choice is a genuine judgment call and say why.

## Step 4 — Write the plan file

Write to `plans/PLAN-<YYYY-MM-DD>-<short-slug>.md` in the repository root
(create `plans/` if missing). Use exactly this structure:

```markdown
# Plan: <objective, one line>

Date: <YYYY-MM-DD> · Source prompt: <one-line paraphrase>
Estimated sessions: <n> · Models used: <list>

## Objective
<2-4 sentences: what is being built/changed and why, in plain language.>

## Deliverables
- <artifact 1 — exact path/location>

## Assumptions (made because the prompt did not specify)
- <assumption> — chosen because <reason>. If wrong, affects tasks <IDs>.

## Open questions (answers change the plan)
- <question> — blocks task <ID> / changes phase <N>.

## Phase 1 — <name>
### Task 1.1 [model: <Model> | effort: <level>] [P if parallelizable]
**Context:** <why this exists>
**Inputs:** <paths, URLs, branches>
**Work:** <detailed instructions, scope fence included>
**Output:** <exact artifact>
**Acceptance:** <testable criteria / command + expected result>
**Depends on:** <task IDs or none>

<repeat per task, per phase>

## Token-optimization notes
- <where the big token costs are and how the routing avoids them>
- <what to batch, what to cache, what NOT to spawn subagents for>

## Execution order
<one line per session: which tasks run together, on which model>
```

After writing the file, reply with: the file path, the phase/task count, the
model distribution (e.g. "7 tasks: 2 Haiku, 4 Sonnet, 1 Opus"), and every
assumption and open question repeated verbatim so the user can correct them
before execution starts.

## Rules

- Never route a task to Fable 5 or Opus 4.8 to "be safe" — that is the
  opposite of this skill's purpose. Justify every Opus+ assignment.
- Never write a task an executor would have to ask a question about; the
  question belongs in the plan, not in the executor's session.
- Keep the plan file additive: re-planning the same objective updates the
  existing PLAN file (mark superseded tasks) instead of creating a duplicate.
- Verify model IDs/pricing against current docs when a new model family has
  shipped since 2026-07; do not silently trust the table above forever.
