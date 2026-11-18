# change-guard

A pull request check that asks one question of every change: do the tests that come with it actually test it?

Version 0.3.0, a pre-release. It works on small projects and has run on GitHub Actions with Python and with ten test runners for other languages (see "Languages"), but it has not been used on a large codebase yet. Read "Limits, stated plainly" before you rely on it.

## The problem

A change can arrive with tests that pass no matter what the change does, whoever wrote them, and more and more changes and their tests are written by an AI coding tool in one go. A test that only calls the new function, mocks it, or checks that it exists will pass on the old code and on the new code alike, so a green test run tells a reviewer nothing about the change. The change guard runs the new or changed tests against the code before the change and against the code after it, and stops the pull request when those tests would not have noticed the change being wrong.

## What it does on a pull request

The rule: a change to the paths you protect must bring a new or changed test, and that test must fail on the base commit (the merge base with the target branch) and pass on the change. Only the changed test files run, so a large suite does not run in full.

In short, for every pull request it:

1. Reads its configuration from the target branch, never from the pull request.
2. Sorts the changed files into protected files, test files, exempt files and others.
3. Lets the change through without running anything when no protected file changed, or when the change is a pure rename, a whitespace-only edit of Python files with the same syntax tree, or an edit of files that were already marked as generated.
4. Stops a change to protected files that brings no test.
5. Runs the changed tests on the head commit (they must pass), then on the base commit with the head's test files laid over it (they must fail, for a reason that counts), then on the base a second time (the result must be the same).
6. For new Python functions, runs the tests once more with each new function's body replaced by `return None`: at least one test must notice.
7. Prints one result, one sentence with the cause, any notes for the reviewer, and appends exactly one line to a log.

[docs/how-it-works.md](docs/how-it-works.md) has the full decision flow and every result and cause code.

### The three basic cases

These are the real messages from the seeded cases in `seed_cases.py`, in blocking mode (commit ids shortened).

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

In report-only mode (the default) a run that would stop the merge also prints `REPORT ONLY: in blocking mode this run would stop the merge; nothing is blocked now.` and the check stays green.

## Quick start: GitHub Actions in five minutes

You need a repository whose test runner can run a given list of test files and write a per-test report the guard reads (Python's `unittest` or pytest, or one of the runners under "Languages"), and a runner with git and Python 3. There are two routes. Both read the configuration from the target branch, run in report-only mode by default and keep one log line per run.

### Route 1: the action (recommended)

1. Copy `change-guard.example.json` to `change-guard.json` at the repository root and set `protected`, `tests` and `test_command` for your project (see "Configuration" below). Add `.change-guard/` to `.gitignore`.
2. Add a workflow `.github/workflows/change-guard.yml` with the `pull_request` trigger, a read-only token, a checkout with full history, and this step:

```yaml
      - name: Change guard
        uses: m-atek/change-guard@[[COMMIT HASH OF THE RELEASE]] # v0.3.0
        with:
          mode: ${{ vars.CHANGE_GUARD_MODE || 'report' }}
```

3. Open a pull request with these files.

[docs/github-action.md](docs/github-action.md) has the complete workflow to copy, the inputs and outputs, how to make the check required, the skip step, and what the action does not do. Pin the action to the full commit hash of a release, never to a branch. The action runs the guard from its own files at that commit, never from the pull request, and uses no other action inside it. Never use it as `uses: ./` in the repository it checks: that would run the pull request's own copy of the guard. Its outputs (`result`, `cause`, `blocks`, `log-line`) are for information; the check passes or fails on the guard's exit code, and `blocks` follows that exit code.

### Route 2: copy the files

For teams whose policy does not allow third-party actions.

1. **Copy three files** into your repository:
   - `change_guard.py` and `cg_unittest_report.py` to `tools/change-guard/`
   - `change-guard.example.json` to `change-guard.json` at the repository root, then set `protected`, `tests` and `test_command` for your project (see "Configuration" below).
2. **Add one workflow:** copy `ci/github-actions.yml` to `.github/workflows/change-guard.yml`. Put the setup steps your tests need (for example `actions/setup-python` and installing dependencies) where the file says so.
3. Add `.change-guard/` to `.gitignore`, so the log does not show up as a changed file.
4. Open a pull request with these files. Because the target branch has no guard yet, this one pull request runs the copy it brings and says so (note `config-from-head`). From the next pull request on, the guard, its reporter and its configuration are always taken from the target branch, so a pull request cannot change the rules it is judged by.

### For both routes

**Report-only by default.** The check is always green and the job output and step summary say what blocking mode would have done. Watch it on real pull requests for a while before you switch.

**Switching to blocking.** Set the repository variable `CHANGE_GUARD_MODE` to `block` (Settings, Secrets and variables, Actions, Variables). Then make the job `change-guard` a required status check in your branch rules; in report-only mode it is always green, so you can require it from the start. On GitHub's free plan a private repository cannot make a status check required: the check turns red, but merging is not blocked. Public repositories and paid plans can require it. The label `change-guard-enforce` puts a single pull request in blocking mode, which is useful for a trial run; it can only make the guard stricter.

**The skip label.** Some changes really cannot carry a test. Add the label `change-guard-skip` to the pull request and a line in its description:

```
Change-Guard-Skip-Reason: Urgent fix for the checkout total; the test follows in the next pull request
```

The guard then passes the change as SKIPPED and writes into the log who added the label (read from the pull request's event history) and the reason. A label without a reason of at least ten characters is refused (STOPPED, `skip-no-reason`), and if the person who added the label cannot be read, the guard fails closed. Removing the label ends the skip on the next run.

**Protect the guard itself.** GitHub takes the workflow file from the pull request, so a pull request can change the pinned action or the workflow. Protect `.github/workflows/`, `change-guard.json` and, on route 2, `tools/change-guard/` with a CODEOWNERS rule and turn on "Require review from Code Owners" in the branch rules. Keep the workflow's `pull_request` trigger and its read-only token, and give the job no secrets: it runs the pull request's own test code.

## Configuration

`change-guard.json` sits at the repository root and is read from the base commit, so a change to it takes effect for the pull requests after it is merged. Keys that start with an underscore are comments. Unknown keys are refused, so a typo cannot silently weaken the guard. `change-guard.example.json` lists every common key at its default.

The keys you will set:

| Key | Meaning | Default |
|---|---|---|
| `protected` | Path patterns whose changes need a test | required |
| `tests` | Patterns that identify test files | required |
| `test_command` | Command that runs a given list of test files and exits non-zero on a failure. Placeholders: `{files}`, `{dirs}`, `{classes}`, `{classes_csv}`, `{gradle_tests}`, `{dotnet_filter}`, `{names_regex}`, `{python}`, `{report}`, `{cg_tools}` | required |
| `report_format` | The per-test report the test command writes: `none`, `unittest-json`, `junit-xml`, `go-json`, `jest-json`, `rspec-json`, `dotnet-trx`. `none` falls back to exit codes | `none` (the example file sets `unittest-json`) |
| `exempt` | Patterns that pass untouched (documentation, dependency bumps) | `[]` |
| `test_support` | Helper files laid over the base with the tests but not run (fixtures, `conftest.py`) | `[]` |
| `setup_command` | Command run in each worktree before the tests, for example installing dependencies | none |
| `pass_env` | Environment variables the tests may see beyond the plain ones (names or patterns such as `JAVA_*`). CI tokens and CI control files can never be named here | `[]` |
| `mode` | `report` or `block`; the `CHANGE_GUARD_MODE` environment variable overrides it | `report` |
| `time_budget_seconds` | Time budget for the whole run | 300 |

Settings for the deeper checks, all optional:

| Key | Meaning | Default |
|---|---|---|
| `report_path` | For runners that write their report to a fixed place inside the worktree (Gradle, Maven, `dotnet test`) | none |
| `base_error_policy` | What happens when the only evidence on the base is that new code is missing and no probe covered it: `probe` and `note` pass it as `ok-unproven` with a sentence for the reviewer, `stop` stops it | `probe` |
| `probe` | `auto` (Python probe when protected `.py` files changed), `off`, `python`, or `command` (your own mutation tool in `probe_command`) | `auto` |
| `probe_scope` | `each`: every added function must be noticed; `any`: one run with all new bodies emptied | `each` |
| `probe_ignore` | Function names the probe leaves alone | `["__repr__", "__str__", "_log*"]` |
| `probe_time_budget_seconds` | The probe's own time box inside the whole budget | 120 |
| `base_repeats` / `head_retries` | Base runs that must agree (1 or 2), retries of a failing head run (0 or 1) | 2 / 1 |
| `errored_counts_as_proof` | Whether an unexplained exception on the base counts as proof | true |
| `auto_exempt` | Which automatic exemptions apply: `whitespace`, `rename`, `generated` | all three |
| `check_edited_tests` | Runs the old version of each edited test on the new code: `false`, `true` (a note) or `"stop"` | false |
| `inconclusive_exit_codes` | Exit codes of the test command that prove nothing (pytest: `[3, 4]`) | `[]` |
| `missing_symbol_patterns`, `environment_error_patterns` | Extra patterns added to the built-in lists | `[]` |
| `notes`, `overlay_added_files`, `generated_markers`, `snapshot_patterns`, `guard_files`, `log_file`, `skip_reason_min_length`, `output_tail_lines`, `suspect_base_failure_patterns` | See [docs/how-it-works.md](docs/how-it-works.md) | |

Pattern rules: `**` matches any number of folders, `*` matches inside one folder name, `?` one character. A pattern without a slash matches the file name in any folder, as in `.gitignore`. A file that matches a test pattern is a test, even inside a protected folder. Exempt wins over protected.

For pytest, use:

```json
"report_format": "junit-xml",
"test_command": "{python} -m pytest -q -p no:cacheprovider --continue-on-collection-errors --junit-xml={report} {files}",
"inconclusive_exit_codes": [3, 4],
"test_support": ["tests/**/conftest.py"]
```

Keep `--continue-on-collection-errors`: without it, one test file that does not load on the base stops pytest before it runs the others.

Run it by hand from the repository root:

```
python3 tools/change-guard/change_guard.py --base origin/main --head HEAD --config change-guard.json --explain
```

Other options: `--repo`, `--mode`, `--log`, `--ref` (a label such as `pr-42` for the log), `--skip-by` and `--skip-reason` (or `CHANGE_GUARD_SKIP_BY` and `CHANGE_GUARD_SKIP_REASON`), `--time-budget`, `--summary` (appends Markdown, for example to `$GITHUB_STEP_SUMMARY`), `--result-json` and `--version`. In blocking mode the exit code is 1 for STOPPED and TIMEOUT and 2 for ERROR; in report mode it is always 0.

## What it supports today

- **Python with unittest:** built in. `cg_unittest_report.py` runs unittest files and writes the per-test report (`unittest-json`). Run for real, locally and on a GitHub hosted runner.
- **Python with pytest:** built in through pytest's own JUnit XML report (`junit-xml`). Run for real with pytest 9.2.0 on Python 3.11.6 on a developer machine and, since 18 November 2026, with pytest 9.2.0 on Python 3.14.10 on a GitHub hosted Linux runner (run 44352029536): the five seeded cases, and the built-in probe stopped a new function's call-only test (`probe-passes`) and passed its real test (`ok-new-code`).
- **The neutral-body probe:** built in for Python only.
- **Other languages:** Vitest, Jest, Maven with JUnit 5, Gradle with JUnit 5, Kotlin through Gradle, `go test`, `dotnet test` with xUnit, PHPUnit, RSpec, and `swift test` with XCTest and with Swift Testing ran for real on a GitHub hosted Linux runner, through each runner's own report (see "Languages" and [docs/languages.md](docs/languages.md)). Without a probe for your language, a test that only calls new code passes as `ok-unproven` with a sentence for the reviewer, unless you set `base_error_policy` to `stop`. Other runners were tested on hand-written sample files only or not at all. Xcode projects, `xcodebuild` and macOS runners were not run, and Xcode result bundles are not read. `probe_command` has not been tried with any real mutation tool.
- **Requirements:** git and the Python 3 standard library, nothing to install. The code parses with the Python 3.8 grammar, but Python 3.8 has not been run; Python 3.9 to 3.15 have (see "How it was tested"). Git 2.51.2, Apple git 2.54.0 and git 2.56.1 have run; 2.17 is the expected minimum (the first version with `git worktree remove`), which is an estimate, not a test.
- **CI platforms:** `action.yml` packages the guard as a GitHub Action ([docs/github-action.md](docs/github-action.md)), and example files for GitHub Actions, GitLab CI, Jenkins and Azure DevOps are in `ci/`. Only the GitHub Actions workflow in `ci/` has run on its platform. See [docs/ci-platforms.md](docs/ci-platforms.md).
- **Operating systems:** Linux and macOS. Windows agents have not been run, and the guard stops a leftover test process group on Unix only.

## Languages

The core check is the same for every language: the guard runs your test command on the head and on the base and reads the runner's per-test report. On 18 November 2026 it ran on GitHub's hosted Linux runner (ubuntu-26.04) with ten runners outside Python, each on a tiny demonstration project in `tests/polyglot/` with five seeded changes, and every case gave the documented result (workflow `.github/workflows/polyglot.yml`, runs 44338193666 and, for Gradle, Kotlin and Swift, 44343395672):

- TypeScript with Vitest 3.2.4 (`jest-json`)
- JavaScript with Jest 29.7.0 (`jest-json`)
- Java with Maven 3.9.15, Surefire 3.5.2 and JUnit 5 (`junit-xml`)
- Go 1.27.4 with `go test -json` (`go-json`)
- C# with `dotnet test`, xUnit 2.9.3 and the TRX logger (`dotnet-trx`, new in 0.3.0)
- PHP with PHPUnit 11.5.58 (`junit-xml`)
- Ruby with RSpec 3.13 (`rspec-json`)
- Java with Gradle 9.9.1 and JUnit 5 (`junit-xml`)
- Kotlin 2.4.21 with Gradle 9.9.1 and kotlin.test (`junit-xml`)
- Swift 6.4.2 on Linux with `swift test` and XCTest (`junit-xml`)
- Swift 6.4.2 on Linux with `swift test` and Swift Testing (`junit-xml`)

Python with pytest 9.2.0 ran in the same workflow (run 44352029536); there the built-in probe judged the new-function cases, so a test that only calls a new function was STOPPED (`probe-passes`).

Xcode projects and `xcodebuild` on macOS were not run.

In each of them a change with no test and a test that also passes without the change were stopped, a test that checks a changed behaviour passed as `ok`, and a test that fails on the base only because a new function is missing there was read from the compiler's or runtime's own message as "new code is missing", never as proof.

**The built-in probe exists for Python only.** Outside Python, a change that adds a new function cannot be proven by the base run, because its test fails there only because the function does not exist. Such a change passes as `ok-unproven`, with a sentence saying the guard could not show that the test checks the new code, the note `probe-unavailable` and, on GitHub, a warning annotation. The guard cannot tell a test that only calls the new function from one that checks its result: both pass that way. Set `base_error_policy` to `stop` to stop both, or use a runner option that fails a test without assertions (PHPUnit's `--fail-on-risky` and Vitest's `--expect.requireAssertions` were run). [docs/languages.md](docs/languages.md) has the table with the runner versions, how each report is read, the ready-to-copy configuration and the differences between runners.

## Limits, stated plainly

**It is not a security boundary.** The tests of a pull request run on the same build agent as the guard, as the same user, with the same rights. Test code written on purpose to attack the guard can get a change through. In a separate verification round, a background process started by the tests, which wrote into the guard's other working copies as soon as it was up, got a gamed change through ten runs out of ten. The guard catches several such attempts and ends the run as ERROR `tampered`, and a reviewer who reads the test code would see one, but only isolation closes this route: each test run in its own container, or the tests under a user account that cannot write to the guard's folders. The guard does not do that by itself. It is not a claim that the guard cannot be gamed.

**It shows that a test depends on the change, never that the change is right.** A test with a real assertion that checks the wrong value passes. Someone still reads the assertions.

**A test written to lie can still tell the phases apart.** The guard hides which commit a test runs on from the environment, folder names, `git status` and `git log -1`, but `git log -1 --stat`, `git log --skip=1`, `HEAD~1`, or a counter kept outside the working copies still differ between the runs. Test code can also rewrite its own report after the runner wrote it.

**What the tests can reach.** They can read any file the job's user can read and write outside the watched files and folders. A process they start can outlive the guard and write to the log after its check. A `~/.gitconfig` they write stays on the agent (the guard does not read it; other jobs may). Give the job no secrets, and a variable you name in `pass_env` reaches the tests.

**The pipeline file comes from the pull request.** Every supported platform takes the workflow or pipeline file from the change, at least for trusted contributors. Only a CODEOWNERS rule (or required reviewers for those paths) closes that, and you set it.

**The probe has gaps.** It is built in for Python only. It covers functions the change adds and functions whose signature gains a parameter, not changed bodies of existing functions (the base run does that job). A module-level constant, a callable that is not a `def` or a lambda (for example `functools.partial`) and a class without methods get no probe. A change that adds one parameter and removes another passes as `ok-unproven` when its test only passes the new one. A rewritten function that breaks the import of a test file counts as noticed, so a module built to need the new function at import time gets past the probe with a weak test. Without the probe, a test that only checks that a new name exists passes.

**False stops.** A new function defined for another platform, inside an `if` that is false on the agent, cannot be noticed by any test there, so the change is stopped; use `probe_ignore` or the skip step. A test that rightly asserts that a new function returns `None` is stopped by the probe. An honest test that leaves a tracked file of its working copy changed, or that changes the repository's git configuration, ends the run as ERROR `tampered`.

**One failing test is enough.** If at least one changed test fails on the base for a reason that counts, the change passes. New tests that also pass on the base get a note, not a stop. A test of an existing function that fails on the base by an assertion unrelated to the behaviour (for example on a version string the change bumps) counts as proof.

**Exemptions and the skip step are doors, on purpose.** A pure rename that breaks imports passes as EXEMPT `pure-rename`. A pull request that only repairs a broken configuration passes as EXEMPT `config-repair` and may loosen the rules for the changes after it. Anything on the exempt list passes without a look. Every EXEMPT and SKIPPED run is in the log with its cause, so you can count them later. Nobody with admin rights is stopped from removing the required check.

**The edited-tests check can be defeated.** It is off by default. It runs in the head working copy, which the head run can change, so a test written to lie gets past it.

**Base, not tip.** The guard compares against the merge base, the code the change was written against. If the target branch has moved, your normal test job covers the newest code.

**Flaky tests.** The second base run names a test that changes its result between two runs, and one head retry absorbs a single failure. A test that is flaky but gives the same result twice in a row still passes or fails by luck.

**Patterns and parsers outside Python have run on one runner image only.** The missing-symbol patterns and report parsers for Vitest, Jest, Maven and Gradle (javac), Kotlin, Go, the C# compiler, PHPUnit, RSpec and Swift were matched against real output on one GitHub hosted Linux image, with one version of each runner, on demonstration projects. The patterns for plain Node.js ES modules and TypeScript's own compiler were matched only against samples written by hand, and Swift's messages from Xcode were not seen. Check them against one real error from your own runner before you rely on them.

**Untested ground.** Large repositories and monorepos (up to three working copies per run cost time and disk), Git LFS (LFS files stay pointer files in the working copies), submodules, symbolic links in laid-over files, a checkout owned by another user, pull requests from forks, Windows and macOS runners, and every CI platform except GitHub Actions. Outside Python also: other runner versions, multi-module builds and monorepos.

**Run time.** A passing run costs one head run, two base runs and one probe run per added function. On the small demonstration project that was under a second. In a real pipeline, expect roughly twice the time of the changed tests plus one run per added function; that is an estimate, not a measurement.

[docs/edge-cases.md](docs/edge-cases.md) explains how the guard handles the common ways to game the rule, and where it cannot.

## How it was tested

Everything below holds for a small demonstration project (a tiny shop module with a standard library unittest suite, built by `seed_cases.py`), on one macOS developer machine and, since 18 November 2026, on a GitHub hosted Linux runner. The guard has not run on a production codebase.

- **Unit tests:** 143 unit tests pass at version 0.3.0 (`tests/`), on the developer machine (Python 3.11.6, git 2.51.2) and on the hosted runner under Python 3.10 to 3.14 (run 44352029682). Version 0.2.2 had 118, which also passed in a separate run and in the release folder.
- **Seeded cases:** `seed_cases.py` builds a throwaway repository and runs the guard on 47 seeded, edge and library cases plus a series of ten normal changes, 57 guard runs per round. In two separate verification rounds, and once more afterwards, both basic bad cases were stopped with a one-sentence cause, 23 of 23 gaming cases were stopped, and 11 of 11 honest changes passed. The ten normal changes in a row gave no false stop, with unittest and with pytest, in four rounds.
- **pytest:** a ported series of 43 cases ran with pytest 9.2.0 on Python 3.11.6, 43 of 43 as documented, in two rounds.
- **The log:** every run wrote exactly one log line in the stable 19-column format, 57 for 57 runs with unittest and 53 for 53 with pytest, including skipped runs with who and why.
- **Python and git versions:** the separate verification round ran on Python 3.11.6 with git 2.51.2. The author's own runs of the 118 unit tests of 0.2.2 and one full round of seeded cases also passed under Python 3.9.6, 3.13.18, 3.14.5 and 3.15.2 on the same machine (with git 2.51.2 or Apple git 2.54.0), and under Python 3.10.22, 3.11.18, 3.12.16, 3.13.18, 3.14.4 and 3.14.10 on the hosted runner (git 2.56.1), in two runs. Python 3.9 is not offered for that runner image. pytest ran under Python 3.11.6 on the developer machine and under Python 3.14.10 on the hosted runner (run 44352029536).
- **First run on a hosted runner (GitHub Actions, 18 November 2026):** in a private demonstration repository built with `seed_cases.py --export`, on GitHub's hosted Linux runner (image ubuntu-26.04, git 2.56.1, Python 3.14.4), pull request 1 (no test) ended STOPPED (`no-test`), pull request 2 (a test that also passes without the change) ended STOPPED (`test-passes-on-base`) and pull request 3 (a test that checks the change) ended PASSED (`ok`), each with the same sentence as locally. The skip label with a reason ended SKIPPED and the log line named who set the label and the reason; the label without a reason was refused. In report mode the check stayed green while the result line said STOPPED, and the enforce label turned the same pull request red. After the main branch moved by one commit the results did not change. Not covered by that run: other CI platforms, pytest on a hosted runner (it ran later, in run 44352029536), Windows and macOS runners, pull requests from forks and a blocked merge (the repository was private on the free plan, so the check could not be made required).
- **Other languages (GitHub Actions, 18 November 2026):** the workflow `.github/workflows/polyglot.yml` ran the guard in blocking mode on seven demonstration projects (Vitest, Jest, Maven with JUnit 5, Go, .NET with xUnit, PHPUnit, RSpec) on GitHub's hosted Linux runner, 53 guard runs in all, every one with the expected result and cause (run 44338193666). A later run (44343395672) added four more (Gradle with JUnit 5, Kotlin, Swift with XCTest, Swift with Swift Testing), 28 more guard runs, all as expected, with 20 to 31 seconds per guard run for Gradle and Kotlin and 12 to 16 seconds for Swift. An earlier run of that workflow (run 44335953379) found two defects, fixed in 0.3.0: Jest and Vitest test ids held the worktree folder, and Vitest's message for a missing function was not recognised, so the missing function counted as proof. A guard run that ran tests took 0.4 to 0.6 seconds with Go, 1.2 to 3.1 seconds with RSpec and PHPUnit, 3.2 to 6.9 seconds with Vitest and Jest, and 9.2 to 13.2 seconds with Maven and .NET, mostly the runners' own start-up and build time.
- **Time:** on the demonstration project the guard took a median of 0.46 seconds per code change with unittest, and 0.86 to 0.87 seconds with pytest against 0.12 seconds for a plain pytest run of the same file. On the hosted runner the median was 0.12 to 0.19 seconds over 56 runs, and a whole pull request job took 6 to 14 seconds. On a repository with 20,000 extra files an honest change took about 5.3 seconds. These numbers say nothing about your suite.

## How this was built

The first versions of this tool were written with heavy use of AI coding tools and reviewed by AI tools, including the verification rounds above. That is why the limits and the test evidence are spelled out in this much detail: you should be able to check every claim here against the code and the tests yourself. [CHANGELOG.md](CHANGELOG.md) lists what each review found and what changed.

## Paid help

The author also offers a paid service around this tool: installing it in a team's own pipeline, with tests agreed in advance and a warranty. Details: https://es.nl/pipeline-guard/. The tool itself is free to use under the Apache License 2.0; you do not need the service to use it.

## Reporting a problem

Open an issue with the guard's full output (the lines from `change-guard 0.3.0 | mode ...` to `log: ...`), your `change-guard.json`, the git and Python versions, the CI platform, and, if you can, a small repository or a script that reproduces it. [CONTRIBUTING.md](CONTRIBUTING.md) says what a good report contains. For a security problem, do not open a public issue; see [SECURITY.md](SECURITY.md).

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
