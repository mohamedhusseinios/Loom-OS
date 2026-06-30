# Context

## Current Task
Shipped "merge target branch selection" — the task drawer's Merge button now lets the user pick which branch (local or remote) a finished task merges into. Delivered as PR #8 on `feat/merge-target-branch-selection`.

## Key Decisions
- Off-target merges run in a throwaway git worktree so the user's working checkout is never switched; merging into `origin/X` creates a local `X` and does NOT push.
- Merge endpoint takes an optional `{target, remote}` body and stays backward compatible (no body → current branch); response gained a `target` field.
- Dropdown default = the repo's current branch.

## Next Steps
- Review/merge PR #8 (https://github.com/mohamedhusseinios/Loom-OS/pull/8).
- Optional follow-ups (in PR/ledger): unit test for `remote` defaulting to False; visually distinguish remote options in the `<select>`.
- Real end-to-end UI smoke (click Merge on a done task with a live daemon + dashboard) — not yet exercised.
