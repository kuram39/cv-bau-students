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

## Branch protection enforcement

Hard branch protection on `main` (blocking a merge until `ci` is green)
requires **GitHub Pro** for a *private* repo, or making the repo
**public**. On the current free + private tier the rule can't be set
via the API (`403: Upgrade to GitHub Pro or make this repository
public`).

What still works without it:
- **CI runs on every PR and every push** — the red/green status is
  visible on each PR; the convention is *do not merge a red PR*.
- The branch → PR flow gives the audit trail regardless of enforcement.

To turn on hard enforcement, pick one:
1. **GitHub Pro** (~$4/mo) → then run:
   ```bash
   gh api -X PUT repos/buhlez31/cv-bau-students/branches/main/protection \
     --input - <<'JSON'
   {
     "required_status_checks": {"strict": true, "contexts": ["ci"]},
     "enforce_admins": false,
     "required_pull_request_reviews": {"required_approving_review_count": 0},
     "restrictions": null
   }
   JSON
   ```
   Or in the UI: **Settings → Branches → Add branch ruleset →** target
   `main`, require status check `ci`, require a PR before merging.
2. **Make the repo public** → the same API call / UI path works for free.

## Notes

- **Solo repo:** the gate is a passing CI check and a PR — it does not
  require a second reviewer's approval (there isn't one). The value is
  the audit trail + the merge gate, not human review.
- **No secrets in CI:** tests mock all LLM calls and use an in-memory
  SQLite fixture, so CI needs no `ANTHROPIC_API_KEY`.
- **The owner keeps an escape hatch:** `enforce_admins` is off, so the
  repo owner can push a hotfix directly to `main` in an emergency.
  Use sparingly — it bypasses the gate.
