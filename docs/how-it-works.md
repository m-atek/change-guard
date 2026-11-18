# How the change guard works

This page follows one run of `change_guard.py` from the changed files to the result, in the order the code does it, and lists every result and cause code with the sentence the guard prints. The function names in brackets point into `change_guard.py`.

## The decision flow

```
configuration from the base commit --> merge base, changed files sorted
        |
        +- skip requested? ----------------- yes -> SKIPPED (or STOPPED if who or why is missing)
        +- no file changed / no protected file ----> OUT_OF_SCOPE or EXEMPT
        +- pure rename / whitespace / generated ---> EXEMPT
        +- protected change without a test file ---> STOPPED no-test
        |
        +- prepare the head, base and probe worktrees (before any test runs)
        +- head run: changed tests must pass ------> STOPPED test-fails-on-head / no-test-collected / no-test-ran
        +- base run: changed tests must fail ------> STOPPED test-passes-on-base, ERROR base-error-unrelated
        +- second base run: same result? ----------> STOPPED flaky-on-base
        +- probe for new Python functions ---------> STOPPED probe-passes
        +- edited-tests check (optional) ----------> note, or STOPPED edited-test-would-fail
        |
        +- verdict -> PASSED ok / ok-new-code / ok-unproven, or STOPPED base-error-only
```

At the end of every run, whatever happened, the guard checks that the tests did not tamper with its files, removes its worktrees, prints the result, and appends one log line.

### 1. Configuration (`load_config_from_commits`, `validate_config`, `config_unloadable`)

The guard reads `change-guard.json` as committed on the base commit given with `--base`, never the copy in the change. If the base has no configuration, which is only the case for the pull request that installs the guard, it uses the head's copy and adds the note `config-from-head`. A `--config` path outside the repository is read from disk, because the CI file chose it. Unknown keys and wrong values are refused.

If the configuration cannot be loaded, the guard does not stop there: a skip request with a person and a reason passes the change as SKIPPED with the note `config-broken`, and a change whose only changed file is the configuration passes as EXEMPT `config-repair` when the base's copy cannot be loaded and the head's can. Anything else ends as ERROR `config`.

From here on, every git command runs with hooks switched off and without the user's or the system's git configuration (`_git_setup`, `git`).

### 2. The change (`evaluate`, `raw_changes`, `changed_files`)

The guard takes the merge base of the two commits as "the base": the code the change was written against. It lists the changed files and sorts each into one group: test files (by the `tests` patterns), exempt files, protected files and other files. A renamed file counts under its old and its new path. A change to the configuration or to the guard's own files (`guard_files`) gets the note `guard-changed`.

### 3. Skip, scope and automatic exemptions

- A skip with a person and a reason of at least `skip_reason_min_length` characters passes as SKIPPED and is recorded. A skip with no person or a short reason is refused.
- No changed file: OUT_OF_SCOPE `no-change`. No protected file: EXEMPT `exempt-only` when every changed file is exempt, OUT_OF_SCOPE `no-protected-change` otherwise.
- Every protected change is a rename with identical content (git status `R100`): EXEMPT `pure-rename`.
- Every changed protected file is a Python file changed only in whitespace or blank lines, parses to the same syntax tree on both commits, and keeps a `#!` first line byte for byte: EXEMPT `whitespace-only`. Other file types are never exempt this way, because a carriage return or a trailing space can change what a shell script, a Makefile or YAML block text does.
- Every changed protected file was modified, and carries a generated-code marker in its first five lines on the base and on the head: EXEMPT `generated`. A change cannot exempt itself by adding a marker.
- A protected file changed and no test file was added or changed: STOPPED `no-test`.

### 4. The worktrees (`add_worktree`, `seal_commit`, `WorktreeSeal`, `RepoWatch`)

Before any test runs, the guard prepares every temporary git worktree, each in a folder with a random name under one temporary folder:

- the head;
- the base, with the head's version of the changed test files, matching `test_support` files and (with `overlay_added_files`) every file the change adds outside the protected paths laid over it. A protected file the change renames keeps its old content under its new name, so a test that imports the new name meets the old code;
- when the probe will run, a second copy of the head.

It commits its own changes in each with one neutral message, author and date (an empty commit on the head), so `git status` is clean in all of them and `git log -1` shows the same message. It then records the state of the repository's hooks, git configuration and `info` folder, and checks them before every later git command.

### 5. The per-test results (layer 1)

When the test command writes a machine-readable report (`report_format`), the guard reads each changed test's outcome from it (`read_report` and the `parse_*` functions), and takes the worktree's own folder out of every test id (`relative_records`), because Jest, Vitest and PHPUnit name a test by the absolute path of its file. Without a report it falls back to exit codes.

**Head run.** The changed test files run in the head worktree with a reduced environment (see "What the tests see" below). They must pass; one retry is allowed (`head_retries`), and a pass on the retry adds the note `flaky-on-head`. With a report, a run in which the runner found no test is stopped (`no-test-collected`), and so is one in which every test was skipped or marked as an expected failure (`no-test-ran`). Only tests that passed on the head are judged further.

**Base run.** The guard first checks that the base worktree still holds exactly what it put there (`WorktreeSeal.verify`), then runs the same test files there. Each test that passed on the head gets one class (`classify_base`), checked in this order:

1. Absent from the base report: it takes the class of a load error reported for its file or module, or `not-collected`.
2. `passed` or `skipped` (expected failures count as skipped).
3. A failure whose exception type is an assertion type: `failed-assertion`.
4. Any other failure or error is checked against three lists: a missing-symbol pattern that captures a name the change adds gives `errored-new-symbol`; a message that a file is missing, naming a file the change adds, gives `errored-missing-file`; an environment pattern gives `errored-environment`. Otherwise a failure is `failed-assertion` and an error is `errored-other`.
5. If the runner wrote no report at all on the base (for example a compile step failed first), the end of the output becomes one load error and goes through the same checks.

### 6. The link to the change (layer 2)

A base error counts as "new code is missing" only when the name in the error message is a name the change itself adds in a protected file (`added_symbols`, `missing_symbol_name`): a function, class, top-level name, new module or new parameter. Any other load error is not proof. This is what stops a test that fails on the base only because an unrelated import is broken.

The classes then fall into three groups (`split_classes`):

- **proof:** `failed-assertion`, plus `errored-other` while `errored_counts_as_proof` is true;
- **new code:** `errored-new-symbol` and `errored-missing-file`;
- **neither:** everything else that did not pass.

Early verdicts (`first_decision`): every test passed or was skipped on the base gives STOPPED `test-passes-on-base`; only "neither" results give ERROR `base-error-unrelated`.

### 7. The second base run (layer 4)

Before anything passes, the base runs a second time (`base_repeats`), after the same worktree check. Files the first base run left there, such as caches, are accepted; changed tracked files are not. If any test's class differs between the two runs, the change is STOPPED `flaky-on-base`.

### 8. The neutral-body probe (layer 3)

A base failure that only says "the new function is missing" proves nothing about behaviour, so for Python the guard runs one more check on the head (`run_probe`, `neutralise_python`). Its targets are the functions the change adds and the functions whose signature gains a parameter, in every protected Python file of the change, including functions inside `if`, `try`, `with`, `for`, `while` and `match` blocks and lambdas assigned to a name. Stub bodies (only a docstring, `pass`, `...` or `raise NotImplementedError`) are left out.

For each target in turn (`probe_scope: "each"`), the probe worktree is checked, that function's body becomes `return None` (the docstring stays), the rewrite must compile and leave every other function as it was, and the changed tests run again. The function counts as noticed when at least one test that passed on the head now fails or errors, or when a test file no longer loads. A function no test notices stops the change: STOPPED `probe-passes`. A rewrite that cannot be made ends as ERROR `probe-broken`. The probe has its own time box (`probe_time_budget_seconds`).

With `probe: "command"` the guard runs your own mutation tool instead (`run_probe_command`), restricted to the added names; it must exit 0 when the tests notice every change.

### 9. The edited-tests check (optional)

With `check_edited_tests` on, the version of each edited test file from before the change runs on the head. If it fails there, the guard adds a note, or stops the change when the setting is `"stop"`.

### 10. The verdict (`final_decision`)

- Proof on the base: PASSED `ok`.
- Otherwise new code only: PASSED `ok-new-code` when the probe noticed every added function; when no probe covered it, STOPPED `base-error-only` if `base_error_policy` is `stop`, else PASSED `ok-unproven`.

Without a report, any non-zero exit on the base counts as the failure, and the note `suspect-base-output` flags output that looks like a build or load failure. The second base run and the probe still run, judged on exit codes.

### 11. The end of every run (`main`)

The guard puts back anything the tests changed in the repository's hooks, git configuration or `info` folder, removes every worktree and its temporary folder, and compares the log file, the summary file, its own two scripts and the CI platform's control files with their state before the tests ran. If the tests changed any of them, it removes what was added where it can, and the result becomes ERROR `tampered`. It then prints the result, the cause, the notes and a hint, appends one line to the log, writes the step summary and result JSON if asked, and sets the exit code. An unexpected error anywhere ends as ERROR `internal` with the error in the sentence, never as a traceback without a verdict.

## What the tests see

The tests and the setup command run with an allowlist environment (`command_environment`): the plain variables of the shell and the toolchains (`PATH`, `HOME`, the locale, the temporary folder, `CI`, and locators such as `JAVA_HOME`, `GOPATH`, `VIRTUAL_ENV`, `PYTHONPATH`), the names in `pass_env`, and `CHANGE_GUARD_REPORT` (where to write the report). They never see `GITHUB_ENV`, `GITHUB_OUTPUT`, `GITHUB_PATH`, `GITHUB_STATE`, `GITHUB_STEP_SUMMARY`, `GITHUB_TOKEN`, `GH_TOKEN`, the Actions runtime tokens, GitLab's job tokens, Azure's `SYSTEM_ACCESSTOKEN` or `CHANGE_GUARD_API_TOKEN`, even when `pass_env` names them. Only the setup command also gets `CHANGE_GUARD_PHASE` (`head`, `base` or `probe`) and `CHANGE_GUARD_REPO`, so a test cannot read which commit it runs on from the environment. Worktree folders and report files have neutral names.

## Modes and exit codes

In `report` mode (the default) the exit code is always 0 and the output says what blocking mode would have done. In `block` mode, STOPPED and TIMEOUT exit with 1 and ERROR with 2. The mode comes from `--mode`, else the environment variable `CHANGE_GUARD_MODE`, else the configuration. With `on_timeout: "pass"` a timeout lets the change through and is still logged.

## Results and cause codes

PASSED, EXEMPT, OUT_OF_SCOPE and SKIPPED let the change through. STOPPED, TIMEOUT and ERROR stop it in blocking mode. The sentences below are printed after `cause:`; `%s`-style parts are filled in at run time and shown here in angle brackets.

### PASSED

| Cause | Sentence |
|---|---|
| `ok` | The new or changed tests fail on the base commit by assertion and pass on the head commit, so they show the change in behaviour. |
| `ok` (without a report) | The new or changed test files fail on the base commit and pass on the head commit, so they show the change in behaviour. |
| `ok` (exception as proof) | The new or changed tests raise an exception on the base commit that no missing name explains and pass on the head commit, so they show the change in behaviour. |
| `ok-new-code` | The new tests could not run on the base because the code they call is new in this change, and they fail when that new code is replaced by an empty body, so they depend on what the change adds. |
| `ok-unproven` | The new tests fail on the base only because the code they call is new in this change, and no probe ran, so the guard cannot show that they check its behaviour; a reviewer should read the assertions. (On GitHub Actions this result is a warning annotation, not a notice. Outside Python it is the result for every change that adds a function, whether its test checks it or not; see [languages.md](languages.md).) |

### EXEMPT

| Cause | Sentence |
|---|---|
| `exempt-only` | Every changed file is on the exempt list, so the guard passed this change untouched without running any test. |
| `pure-rename` | The protected files were only renamed, with identical content, so the guard passed this change without running any test. |
| `whitespace-only` | The protected Python files changed only in whitespace or blank lines and parse to the same syntax tree, so the guard passed this change without running any test. |
| `generated` | Every changed protected file carries a generated-code marker, so the guard passed this change without running any test. |
| `config-repair` | The configuration on the base commit cannot be loaded and this change only repairs <file>, so the guard passed it without running any test. |

### OUT_OF_SCOPE

| Cause | Sentence |
|---|---|
| `no-change` | The head commit changes no file against the base, so there is nothing to check. |
| `no-protected-change` | No changed file is under a protected path, so the guard passed this change without running any test. |

### SKIPPED

| Cause | Sentence |
|---|---|
| `skip` | The guard was skipped by <who> with the reason "<reason>", and this run is recorded in the log. (When the configuration could not be loaded, the sentence adds "while its configuration could not be loaded".) |

### STOPPED

| Cause | Sentence |
|---|---|
| `no-test` | This change touches <n> protected file(s) (<files>) but brings no new or changed test file, so nothing shows that its behaviour is tested. |
| `test-passes-on-base` | The new or changed test files also pass on the base commit without this change, so they would not catch the change being wrong. |
| `test-fails-on-head` | The new or changed test files fail on the head commit (exit <n>), so the change does not pass its own tests yet. |
| `no-test-collected` | The changed test files ran on the head commit but the runner found no tests in them, so nothing was tested. |
| `no-test-ran` | Every test in the changed test files was skipped or marked as an expected failure on the head commit, so nothing was tested. |
| `flaky-on-base` | The new tests gave different results in two runs on the base commit, so they cannot show what this change does; make them stable first. |
| `probe-passes` | The new tests still pass when the body of <functions> is replaced by an empty return, so they would not notice that code being wrong. |
| `base-error-only` | The new tests fail on the base only because the code they call does not exist there yet, which shows nothing about behaviour, and the probe is off or not available for this language. |
| `edited-test-would-fail` | The version of <files> before this change fails on the head commit, so the edit to that test may hide a behaviour this change broke. |
| `skip-no-reason` | A skip was requested by <who> without a reason of at least <n> characters, so the skip was refused and the guard did not pass this change. |
| `skip-no-who` | A skip was requested without naming who skipped, so the skip was refused and the guard did not pass this change. |

### TIMEOUT

| Cause | Sentence |
|---|---|
| `time-budget` | The guard stopped after its time budget of <n> seconds while running the tests on the <phase>, so it could not judge this change. |
| `probe-time-budget` | The probe ran past its own time budget of <n> seconds while testing <functions>, so the guard could not show that the new tests depend on that code. |

### ERROR

| Cause | Sentence |
|---|---|
| `config` | Names what is wrong with the configuration, for example: The configuration file has unknown keys (<keys>), so the guard refuses to guess what was meant. |
| `git` | The git command 'git <command>' failed (<message>), so the guard cannot judge this change. Also: the base or head commit is not in this clone; the clone is shallow and does not hold the merge base; the two commits share no history. |
| `command-not-found` | The test command could not start on the <phase> commit (exit <n>), so the guard cannot judge this change. |
| `setup-failed` | The setup command failed on the <phase> commit (exit <n>), so the guard cannot run the tests there; if this is the base, the base may not build. |
| `inconclusive` | The test command ended on the <phase> commit with exit <n>, which the configuration marks as inconclusive, so the guard cannot judge this change. |
| `report-missing` | The test command finished on the head commit but wrote no readable <format> report, so the guard cannot read the per-test results it is configured for. |
| `base-error-unrelated` | The new tests cannot run on the base commit for a reason this change does not explain (<first error line>), so the guard cannot judge this change. |
| `probe-broken` | The guard could not replace the body of <functions> without breaking the file, so it could not run the probe. |
| `tampered` | The test run changed <files>, which belong to the guard, the repository's git setup or the CI platform, so the guard cannot trust this run; what the tests changed in the repository's .git was put back, and text they added to the other files was removed where it could be. For a worktree: The worktree the guard prepared for the <phase> run changed after the guard prepared it (<files>), so the guard cannot trust this run. |
| `internal` | The guard failed with <exception> (<message>), which is a bug in the guard or an input it cannot handle, so nothing was judged. |

## Notes

Notes never change the result. They are printed as lines that start with `note:`, written into the step summary, and their codes go into the last log column: `assertions-removed`, `test-deleted`, `skip-marker-added`, `mocks-new-code`, `snapshot-changed`, `passes-on-base`, `flaky-on-head`, `edited-test-would-fail`, `probe-unavailable`, `probe-partial`, `config-from-head`, `guard-changed`, `config-broken`, `config-repair`, and, without a report, `suspect-base-output`.

## The log

One line per run, appended to `.change-guard/runs.log` (or `log_file`), tab-separated, UTF-8, no header. Tabs and line breaks inside a value become spaces, and an empty value is written as `-`. The first column names the format version, `cg2`; its first 14 columns are those of the older `cg1` format, in the same order.

| # | Column | Example |
|---|---|---|
| 1 | `log_version` | `cg2` |
| 2 | `time_utc` | `2026-11-17T21:15:17Z` |
| 3 | `result` | `STOPPED` |
| 4 | `cause` | `probe-passes` |
| 5 | `mode` | `block` |
| 6 | `ref` | `pr-42` |
| 7 | `base` | first 12 characters of the merge base |
| 8 | `head` | first 12 characters of the head |
| 9 | `seconds` | `0.33` |
| 10 | `protected_files` | `1` |
| 11 | `test_files` | `1` |
| 12 | `skipped_by` | who skipped |
| 13 | `skip_reason` | the reason as given |
| 14 | `message` | the one-sentence cause |
| 15 | `tests_proof` | tests that failed on the base by assertion (or exception, when allowed); `-` without a report |
| 16 | `tests_new_symbol` | tests that failed on the base only because new code or a new file is missing |
| 17 | `tests_other` | tests that failed on the base for a reason that is not proof |
| 18 | `probe` | `-`, `covered`, `not-covered:<names>`, `broken`, `timeout`, `off`, `unavailable`, `command-covered` |
| 19 | `notes` | note codes joined by commas |

A CI artifact expires. If you need the log for longer, ship it to a store you keep. The tests cannot rewrite the lines the guard prints in the job output (`result:`, `cause:`), so those are the record to compare the log with.

## Adapting the test command

The guard needs a command that runs exactly the test files it is given and exits non-zero when one of them fails. It works best when the command also writes a per-test report. The rows marked "ran" have run for real (Python on a developer machine and, for unittest, on GitHub's hosted runner; the others on GitHub's hosted Linux runner since version 0.3.0, see [languages.md](languages.md)); the rest are starting points whose parsers were tested on hand-written samples.

| Stack | `report_format` | `test_command` (and `report_path`) |
|---|---|---|
| Python, unittest (ran) | `unittest-json` | `{python} {cg_tools}/cg_unittest_report.py {report} {files}` |
| Python, pytest (ran) | `junit-xml` | `{python} -m pytest -q -p no:cacheprovider --continue-on-collection-errors --junit-xml={report} {files}`, with `inconclusive_exit_codes: [3, 4]` |
| Java, Maven Surefire (ran) | `junit-xml` | `mvn -B -q -Dsurefire.failIfNoSpecifiedTests=false -Dtest={classes_csv} test`, `report_path: "target/surefire-reports"` |
| PHP, PHPUnit (ran) | `junit-xml` | `vendor/bin/phpunit --bootstrap vendor/autoload.php --log-junit {report} {files}`, with `setup_command: "composer install --no-interaction --no-progress --quiet"` |
| JavaScript, Jest (ran) | `jest-json` | `npx jest --ci --runTestsByPath --json --outputFile={report} {files}`, with `setup_command: "npm ci --no-audit --no-fund --loglevel=error"` |
| TypeScript, Vitest (ran) | `jest-json` | `npx vitest run --reporter=default --reporter=json --outputFile.json={report} {files}`, with the same `setup_command` |
| Go (ran) | `go-json` | `go test -count=1 -json {dirs} > {report}` |
| C#, `dotnet test` (ran) | `dotnet-trx` | `dotnet test <test project> --nologo --logger trx --results-directory TestResults --filter {dotnet_filter}`, `report_path: "TestResults"` |
| Ruby, RSpec (ran) | `rspec-json` | `bundle exec rspec --format progress --format json --out {report} {files}`, with `setup_command: "bundle install --quiet"` |
| Java or Kotlin, Gradle (ran) | `junit-xml` | `gradle --no-daemon --console=plain -q test {gradle_tests}`, `report_path: "build/test-results/test"` (the Gradle wrapper `./gradlew` works the same way, but was not run) |
| Swift packages on Linux, XCTest or Swift Testing (ran) | `junit-xml` | `mkdir -p .build/cg-xunit && swift test --parallel --filter {names_regex} --xunit-output .build/cg-xunit/results.xml`, `report_path: ".build/cg-xunit"` (Xcode projects and `xcodebuild` were not run) |

`{files}` passes paths from the repository root, `{dirs}` their folders, `{classes}` JVM class names, `{classes_csv}` the same joined by commas (for Maven's `-Dtest=`), `{gradle_tests}` the same as `--tests` arguments, `{dotnet_filter}` one `dotnet test --filter` expression that selects the classes named like the test files, `{names_regex}` the test file names as one regular expression (for `swift test --filter`), `{python}` the Python running the guard, `{report}` the report path, `{cg_tools}` the folder that holds the guard. Each worktree is a clean checkout, so dependencies such as `node_modules` must come from `setup_command`.
