# Contributing

This repo uses a lightweight branch → PR → merge flow with a CI gate.
`main` is protected: changes land through pull requests that pass CI,
not direct commits.

## Workflow

1. **Branch off `main`.** Use a typed prefix:
   - `feat/…` — new behaviour
   - `fix/…` — bug fix
   - `docs/…` — documentation only
   - `perf/…` — performance / cost work
   - `chore/…` — tooling, deps, CI

   ```bash
   git switch -c feat/short-description main
   ```

2. **Make the change.** Keep commits focused; one logical change per
   commit where practical.

3. **Run the gate locally before pushing** (same commands CI runs):

   ```bash
   ruff check src tests scripts
   black --check src tests scripts
   pytest -q
   ```

   Optional: `pre-commit` is listed in `requirements-dev.txt` if you
   want these to run automatically on commit
   (`pre-commit install`).

4. **Push + open a PR:**

   ```bash
   git push -u origin feat/short-description
   gh pr create --fill
   ```

5. **CI must be green.** The `ci` check runs ruff + black + the full
   pytest suite on every PR. A red check blocks the merge.

6. **Merge.** Squash-merge into `main`, then delete the branch:

   ```bash
   gh pr merge --squash --delete-branch
   ```

## Notes

- **Solo repo:** branch protection requires a passing CI check and a PR,
  but does not require a second reviewer's approval (there isn't one).
  The value is the audit trail + the merge gate, not human review.
- **No secrets in CI:** tests mock all LLM calls and use an in-memory
  SQLite fixture, so CI needs no `ANTHROPIC_API_KEY`.
- **The owner keeps an escape hatch:** `enforce_admins` is off, so the
  repo owner can push a hotfix directly to `main` in an emergency.
  Use sparingly — it bypasses the gate.
