# RALPH Mode (Autonomous Execution Loop)

This document defines the **Ralph-mode** operating criteria for autonomous task execution in this repository.

## Purpose
Keep the agent in a deterministic execution loop until the active task lock is complete.

## Ralph Criteria (Done Definition)
A task batch is considered complete only when all of the following are true:

1. **Spec alignment**
   - Work is mapped to concrete items from `BREEZE_PRO_AUTONOMOUS_SPEC_v11`.
   - Priority order respected: `P0 -> P1 -> P2 -> P3`.

2. **Code + tests together**
   - Every behavior change includes corresponding tests (new or expanded).
   - If external dependency blocks verification, mark as integration and keep unit CI stable.

3. **Validation gates**
   - Modified Python files pass syntax check (`python3 -m py_compile ...`).
   - Targeted tests for touched areas pass.
   - Repository lint gate (`ruff check .`) passes.

4. **Operational safety**
   - Changes avoid root-level Streamlit refactors unless explicitly required by task.
   - DB and concurrency changes are transaction-safe and thread-safe.

5. **Execution loop bookkeeping**
   - Record what was done, what remains, and next immediate task set.
   - If blocked, log blocker + fallback path and continue with next unblocked task.

## Execution Loop
Use this recurring cycle:

1. Pick next uncompleted highest-priority task.
2. Implement minimal safe patch.
3. Add/update tests for acceptance criteria.
4. Run validation gates.
5. Commit and continue to next task unless task lock ends.

## Task Lock Exit Conditions
Stop autonomous loop only when one of these is true:

- User explicitly changes/ends scope.
- All scoped tasks are complete and validated.
- Hard external blocker prevents further safe progress (must be reported with fallback options).

## Current Focus Baseline
- Continue autonomous completion of remaining v11 tasks.
- Maintain passing unit suite and lint at each iteration.
