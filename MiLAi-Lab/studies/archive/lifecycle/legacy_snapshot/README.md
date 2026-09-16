# Filtered MiLAi experiment snapshot

This directory is a non-executable, filtered copy of experiment-related material from
the legacy MiLAi worktree at Git head
`651099ba8cffc2675961bb9250ba44c158efccb5`.

Included:

- `evals/`, `scripts/`, `research/`, and root `tests/` source;
- root Markdown and experiment audit JSON;
- documentation excluding release/submission archives;
- three experiment-coupled tests excluded from the new Product repository.

Excluded:

- `var`, artifacts, logs, caches, venvs, bytecode;
- wheels, build/dist output, tar/zip releases;
- model files and external benchmark corpora.

`manifest.json` records every copied source and destination digest. This directory is not
on the active package import path.

The legacy root `AGENTS.md` is stored as `MiLAi/AGENTS.legacy.md` so historical agent
instructions cannot override this repository's active instructions.
