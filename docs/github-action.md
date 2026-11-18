# The change guard as a GitHub Action

The change guard runs a fail-to-pass check on every pull request: the tests that a change brings must fail on the code before the change and pass on the code after it. A test that passes either way does not show that the change works, so the guard stops the pull request and says why in one sentence.

`action.yml` at the root of this repository packages the guard as a composite action. Every step is bash and Python 3 from the runner, with the Python standard library only. It uses no other action inside it and pulls in no container image. If your policy does not allow third-party actions, copy the files instead (see "Without the action" at the end).

## Quick start in five minutes

You need a repository whose tests run with Python's `unittest` or with pytest, or with one of the runners in [languages.md](languages.md), on a GitHub hosted Linux runner (or any runner with git and Python 3). For another language, set up its toolchain (for example `actions/setup-node`) in the steps before the action, and put the configuration from languages.md into `change-guard.json`. The action itself has run only on the Python fixture of its self-test; the guard script it runs is the one that ran with the other runners.

**1. Add the configuration.** Copy [`change-guard.example.json`](../change-guard.example.json) to `change-guard.json` at the root of your repository and set three keys for your project:

```json
{
  "protected": ["src/**"],
  "tests": ["tests/**/test_*.py"],
  "test_command": "{python} {cg_tools}/cg_unittest_report.py {report} {files}",
  "report_format": "unittest-json"
}
```

For pytest, see "Configuration" in the [README](../README.md#configuration). Add `.change-guard/` to `.gitignore`, so the log does not show up as a changed file.

**2. Add the workflow.** Save this as `.github/workflows/change-guard.yml`:

```yaml
name: change-guard

on:
  pull_request:
    types: [opened, synchronize, reopened, labeled, unlabeled, edited]

permissions:
  contents: read
  pull-requests: read
  issues: read

concurrency:
  group: change-guard-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  change-guard:
    name: change-guard
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Check out with full history
        uses: actions/checkout@v7
        with:
          fetch-depth: 0
          persist-credentials: false

      # Put the steps your tests need here, exactly as in your normal test job
      # (for example actions/setup-python and installing dependencies).

      - name: Change guard
        uses: m-atek/change-guard@[[COMMIT HASH OF THE RELEASE]] # v0.3.0
        with:
          mode: ${{ vars.CHANGE_GUARD_MODE || 'report' }}

      - name: Keep the log line
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: change-guard-log-pr-${{ github.event.pull_request.number }}-run-${{ github.run_attempt }}-${{ github.run_id }}
          path: .change-guard/runs.log
          if-no-files-found: warn
          retention-days: 90
```

Pin the action to the full commit hash of a release, with the version as a comment, as above. A tag such as `v0.3.0` can be moved by whoever controls the repository; a full commit hash cannot. If your organisation uses workflow lockfiles, the lockfile records the commit for you. Pin `actions/checkout` and `actions/upload-artifact` the same way if your policy asks for it.

**3. Open a pull request** with these two files. The target branch has no `change-guard.json` yet, so this one pull request is judged by the configuration it brings, and the output says so (note `config-from-head`). From the next pull request on, the configuration always comes from the target branch, so a pull request cannot change the rules it is judged by.

**4. Read the result.** The guard writes its verdict into the job log and the step summary of the run. The check stays green in report mode, which is the default, so you can watch it on real pull requests before you let it block anything.

## What a developer sees

These are the real messages of the three seeded cases in `seed_cases.py`, in blocking mode (commit ids shortened). On GitHub the same sentence also appears as an annotation on the run and at the top of the step summary.

**A behaviour change with no test:**

```
changed: 1 protected file, 0 test files, 0 exempt files, 0 other files
  protected: src/pricing.py
result: STOPPED (no-test)
cause: This change touches 1 protected file (src/pricing.py) but brings no new or changed test file, so nothing shows that its behaviour is tested.
what to do: Add or change a test that fails without this change and passes with it, or use the documented skip step.
```

**A behaviour change whose new test also passes without the change:**

```
head: 1 test passed in the changed test files (0.03 s)
per-test results on the base commit:
  passed                 tests.test_bulk.BulkDiscountTest.test_small_order_has_no_discount
result: STOPPED (test-passes-on-base)
cause: The new or changed test files also pass on the base commit without this change, so they would not catch the change being wrong.
what to do: Add an assertion on the behaviour this change introduces, so the test fails on the base.
```

**A behaviour change with a test that checks it:**

```
head: 2 tests passed in the changed test files (0.04 s)
per-test results on the base commit:
  passed                 tests.test_bulk.BulkDiscountTest.test_small_order_has_no_discount
  failed-assertion       tests.test_bulk.BulkDiscountTest.test_ten_items_get_ten_percent_off | AssertionError: 10000 != 9000
base: 1 by assertion or exception (proof), 0 because new code is missing, 0 for other reasons (0.04 s)
base, second run: same result (0.04 s)
result: PASSED (ok)
cause: The new or changed tests fail on the base commit by assertion and pass on the head commit, so they show the change in behaviour.
note: 1 test in the new test files also passes on the base commit: tests.test_bulk.BulkDiscountTest.test_small_order_has_no_discount
```

In report mode a run that would stop the merge also prints `REPORT ONLY: in blocking mode this run would stop the merge; nothing is blocked now.` and the check stays green.

## Making it block, and making the check required

1. **Blocking mode.** Set the repository variable `CHANGE_GUARD_MODE` to `block` (Settings, Secrets and variables, Actions, Variables). The workflow above passes it to the action's `mode` input. In blocking mode STOPPED and TIMEOUT fail the check, and so does ERROR.
2. **Required check.** In a branch rule or ruleset for the target branch, require the status check `change-guard` (the job name). In report mode it is always green, so you can require it from the start.
3. **Plan limit.** On GitHub's free plan a private repository cannot make a status check required. GitHub answers "Upgrade to GitHub Pro or make this repository public to enable this feature." The check still turns red in blocking mode, but merging is not blocked. Public repositories and paid plans can require it.
4. **One pull request at a time.** The label `change-guard-enforce` puts a single pull request in blocking mode, which is useful for a trial. It can only make the guard stricter.

## The skip step

Some changes really cannot carry a test. Add the label `change-guard-skip` to the pull request and this line to its description:

```
Change-Guard-Skip-Reason: Urgent fix for the checkout total; the test follows in the next pull request
```

The guard then passes the change as SKIPPED and records in the log line who added the label (read from the pull request's label history with the job token) and the reason. A label without a reason of at least ten characters is refused (STOPPED, `skip-no-reason`). If the person who added the label cannot be read, the skip is refused too. Removing the label ends the skip on the next run. To turn the skip step off, set the input `skip-label` to an empty string.

## Protect the guard itself

GitHub takes the workflow file from the pull request, so a pull request can change the line that pins the action, or remove the step. Protect `.github/workflows/` and `change-guard.json` with a CODEOWNERS rule and turn on "Require review from Code Owners" in the branch rules. A required workflow lockfile also makes a changed pin visible in review. Keep the `pull_request` trigger and the read-only permissions above, and give the job no secrets: it runs the pull request's own test code.

## Inputs and outputs

| Input | Default | Meaning |
|---|---|---|
| `config` | `change-guard.json` | Configuration file, relative to `working-directory`, read from the base commit |
| `mode` | `report` | `report` or `block`; wins over the `mode` key in the configuration |
| `base` | the pull request's base commit | The guard compares against the merge base of `base` and `head` |
| `head` | the pull request's head commit | The change to judge |
| `skip-label` | `change-guard-skip` | Label that requests the recorded skip; empty turns the skip step off |
| `enforce-label` | `change-guard-enforce` | Label that puts one pull request in blocking mode; empty turns it off |
| `working-directory` | `.` | Folder of the repository to judge |
| `token` | the job token | Used only to read who added the skip label |

| Output | Meaning |
|---|---|
| `result` | `PASSED`, `EXEMPT`, `OUT_OF_SCOPE`, `SKIPPED`, `STOPPED`, `TIMEOUT` or `ERROR` |
| `cause` | The cause code, for example `no-test`; [how-it-works.md](how-it-works.md) lists them all |
| `mode` | The mode the guard ran in |
| `blocks` | `true` when this run fails the check |
| `log-line` | The run's one log line in the `cg2` format |

The outputs are for information, for example for a later step that posts a summary. The check passes or fails on the guard's exit code, not on the outputs. The action reads them from a result file the guard writes at the end of the run, and test code that outlives the guard could change that file; `blocks` therefore follows the exit code, and the action warns when the file disagrees with it. Do not make a later step decide a merge from `result` or `cause`.

Outside a pull request (for example on `push` or `workflow_dispatch`), set `base` and `head` yourself.

## What the action does

1. Refuses to run on `pull_request_target`, and refuses a `mode` other than `report` or `block`.
2. Copies `change_guard.py` and `cg_unittest_report.py` from the action's own files, at the version you pinned, into a fresh folder under `$RUNNER_TEMP`, and runs them from there. It never runs a copy of the guard that the pull request brings.
3. If the skip label is on the pull request, reads who added it and the reason line.
4. Runs the guard with the base and head commits, writes the step summary, prints the log line, appends it to `.change-guard/runs.log` and sets the outputs.

**Never use the action as `uses: ./` in the repository it checks.** `uses: ./` runs the action from the checkout, which on a pull request is the pull request's own copy: the change would bring the guard that judges it. Use the action from the pinned release (`uses: <owner>/change-guard@<full commit hash>`). Only this kit's own self-test uses `uses: ./`, because there the action itself is what is being tested.

## What the action does not do

- **It is not a security boundary.** The tests of the pull request run on the runner as the same user as the guard. Test code written on purpose to attack the guard can still get a change through. The README section "Limits, stated plainly" has the details.
- **It does not prove that a change is right.** It shows that a test depends on the change. Someone still reads the assertions.
- **It does not install your test dependencies.** Put your setup steps before it, as in your normal test job.
- **It does not upload the log as an artifact.** It uses no other action inside it, so the upload is a step in your workflow (the quick start has one).
- **It does not make the check required.** That is a branch rule you set, and on the free plan a private repository cannot set it.
- **It writes nothing to GitHub.** No comments, no labels, no statuses beyond its own step. Its only network call is one read of the label history, and only when the skip label is present. The guard itself makes no network call.
- **It has not run everywhere.** The guard has run on GitHub's hosted Linux runner only: not on Windows or macOS runners, and not on pull requests from forks. The built-in probe for new functions is for Python only, so outside Python a change that adds a function passes as `ok-unproven` with a warning (see [languages.md](languages.md)).

## Without the action

If your policy forbids third-party actions, copy `change_guard.py` and `cg_unittest_report.py` to `tools/change-guard/` and use [`ci/github-actions.yml`](../ci/github-actions.yml). That workflow takes the guard from the target branch with `git show` instead of from the action, and otherwise behaves the same. It is the route that ran on a GitHub hosted runner on 18 November 2026 ([ci-platforms.md](ci-platforms.md)). The action wraps the same steps, and `.github/workflows/action-selftest.yml` runs it on a fixture on every push and pull request to this repository.
