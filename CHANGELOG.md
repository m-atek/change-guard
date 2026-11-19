# Changelog

0.3.1 is the first public version of the change guard. Versions 0.2.2 and 0.3.0 were packaged for release but never published; 0.2.2 corresponds to the internal version 2.2.0, the code that was built, reviewed and first run on GitHub Actions under that number. The version string inside `change_guard.py` (`VERSION`, printed by `--version` and in the first line of every run) reads `0.3.1`, so the tool and these notes agree.

The versions before 0.3.1 are pre-release history. They were built and tested in private between 17 and 18 November 2026 and were never published. Their internal numbers 1, 2.0, 2.1 and 2.2 are mapped to 0.1.0, 0.2.0, 0.2.1 and 0.2.2 below; comments in the code and the tests use the public numbers. The test files `tests/test_v21_fixes.py` and `tests/test_v22_hardening.py` keep their names: they hold the tests for 0.2.1 and 0.2.2.

The ids in brackets (R1 to R20, P1 to P4, K04, V3a to V7, K08, and B1, I1 to I10, D1 to D15 and M1 to M17 of the 0.3.0 audits) are the items of the reviews listed at the end of this file. Every review, verification round and audit listed here was done by AI tools, not by people. Several test classes in `tests/` are named after them.

## 0.3.1, 18 November 2026: fixes from two audits of 0.3.0

Two separate audits of 0.3.0, a code audit and a test audit, both done by AI tools, found one blocking defect and a set of important ones. Each fix below has a regression test (`tests/test_audit_031.py`, `tests/test_ci_files.py`); the limits that remain are in the README section "Limits, stated plainly".

- **B1 (blocking): the action no longer runs a file from the pull request.** Its inline Python ran with the pull request's checkout as the current folder, so a `json.py` there ran inside the action and could record a skip under any name. Every Python call in `action.yml` and in the four CI examples now runs with `python3 -I`, and the skip values reach the guard only when the skip step found the label. `.github/workflows/action-selftest.yml` plants a hostile `json.py` and `sitecustomize.py` in the workspace, with `PYTHONPATH=.`, and checks on every run that neither runs.
- **I1 and D4: a mistyped mode fails closed.** `Block`, `BLOCK` and ` block ` are read as `block`; an unknown value (`blocking`) ends as ERROR `config` with exit code 2 instead of a green check, from `CHANGE_GUARD_MODE`, `--mode` or the `mode` key.
- **I7: folder patterns.** `src`, `src/` and `./src/**` now protect the files under `src/`, as in `.gitignore`, and a protected pattern that matches no file on the base or the head ends as ERROR `config`.
- **I8: `ci/github-actions.yml`.** `persist-credentials: false`; the guard is taken from the base branch before any set-up step and its hash is checked before it runs; the skip values travel as step outputs into the guard step's own `env:`, not through `GITHUB_ENV`. The set-up steps come after these. This version of the file has not run on GitHub.
- **I9: `ci/gitlab-ci.yml`** takes the guard and the base from the tip of the target branch instead of the merge base, and unsets the API token before the guard starts. The token sentences in the documents now say that a token the job holds can be read by the tests from a parent process.
- **D3 (and M2): parallel runs.** A run holds a lock next to the log from before its tests until its line is written, so two guards on one checkout take turns and no line is lost or read as tampering (Unix only).
- **D2 (and M4): report file names.** The head run always wrote `run-1`, so a test could read the phase from its own report path. Every run now gets a random name of one shape. The documents no longer say that a test cannot tell the runs apart; that belongs to "not a security boundary".
- **D1: an untested edit next to a tested new function.** When no test fails on the base by assertion, the result is `ok-new-code` only if every missing name on the base is a function the probe covered (or its class, module or new parameter) and the change edits no existing code; otherwise `ok-unproven` with the note `changed-code-unproven` naming the edited functions, or, outside Python, files (STOPPED `base-error-only` with `base_error_policy: "stop"`).
- **I2 and D6: a missing name is never proof.** `KeyError` is read as a missing name, new class attributes and attributes set on `self` count as new names, and an exception inside a test that names a missing name the change does not add is `errored-unknown-name`: at most `ok-unproven`, never `ok`. `'NoneType' object has no attribute` stays behaviour.
- **I3: edited helpers.** Every file the change adds or edits outside the protected paths is laid over the base, not only test files and added files.
- **I4: word lists.** The environment words apply only to load errors and output without a report; a pytest assertion failure keeps its class; a new test file named in an error no longer reads as a missing file of the change.
- **I5: more declaration forms outside Python:** classes and other types with modifiers, Java and C# methods without an access word, fields and constants, Kotlin and Swift properties, Swift functions with modifiers, JavaScript class methods and CommonJS exports (checked against real javac 21 and node 22 messages in `tests/data/audit-031/`).
- **I6: src layout.** A `PYTHONPATH` entry that points into the checkout is moved to the working copy being run. Golden-file updates, clean-ups that delete code with its tests, and installed packages are documented in the README limits.
- **I10:** the action examples name `<full commit hash of the v0.3.1 release>` with a sentence on what to put there; the real hash is filled in at release.
- **Smaller fixes:** a protected deletion can no longer ride along with a generated-file exemption (M1); `git diff` ignores `.gitattributes` text settings and `.gitattributes` is a guard file (M5); a line break in a file name or test id cannot print a forged line (M6); a file that becomes a folder no longer ends as ERROR `internal` (M7); SIGTERM and Ctrl-C end as ERROR `cancelled` with clean-up and a log line (M3, D12); a test temp folder is removed (M10); GitLab variables that carry the job token are never passed to the tests (M13); git's own `info/refs` is not read as tampering (D5); the probe stops at the first function nobody notices and shortens the name list (D9); one long output line is cut at 2000 characters (D10); a time budget must be above zero (D11); a folder that is not a git repository is named as such (D14).
- **Two existing tests changed:** `test_r9_report_names_are_neutral` asserted the old `run-1` name (D2), and `test_missing_file_environment_skip_and_not_collected` asserted that "Connection refused" inside a test is an environment problem (I4); both now assert the 0.3.1 behaviour.
- `VERSION` set to `0.3.1`. 190 unit tests; `seed_cases.py` unchanged and all as expected.
- Runs on GitHub: unit tests on Python 3.10 to 3.14 (run 44367894420), the action's self-test with the hostile-file case (run 44367894634), and all eleven polyglot jobs (run 44367894438; the Kotlin job passed on its second attempt after a failed download from the Gradle plugin portal). The Kotlin fixture now also looks for plugins on Maven Central.

## 0.3.0, 18 November 2026: other languages on real toolchains

The core check ran on real toolchains outside Python: seven demonstration projects in `tests/polyglot/` (Vitest, Jest, Maven with JUnit 5, Go, .NET with xUnit, PHPUnit, RSpec), and later four more (Gradle, Kotlin, Swift with XCTest, Swift with Swift Testing), each with five seeded changes, on GitHub's hosted Linux runner. An earlier run (run 44335953379) found two defects; both are fixed, and the second run (run 44338193666) gave the expected result and cause in all 53 guard runs. See [docs/languages.md](docs/languages.md).

- **Fixed: Jest and Vitest results never matched across worktrees.** Both runners name a test by the absolute path of its file, and the head, base and probe worktrees are different folders, so no base result could match its head result. The guard now takes the worktree's own folder out of every test id and group (`relative_records`).
- **Fixed: a missing new function counted as proof with Vitest.** Vitest reports it as `TypeError: (0 , formatPrice) is not a function`, which the missing-symbol pattern did not match, so the change passed as PASSED `ok`. The pattern now accepts the closing parenthesis.
- **Jest and Vitest failures name their error class** (`js_error_type`): a matcher failure or an `AssertionError` is an assertion, any other class (`TypeError`, a plain `Error` from the code) is an exception. A failure whose type names such an exception is classified as `errored-other`, not as a failure by assertion, so the sentence no longer says "by assertion" for it, and `errored_counts_as_proof: false` now applies to it.
- **New report format `dotnet-trx`**: the TRX file of `dotnet test --logger trx`, as a file or as a folder (`report_path`), with or without a byte-order mark.
- **New placeholders** `{classes_csv}` (JVM class names joined by commas, for Maven's `-Dtest=`) and `{dotnet_filter}` (a `dotnet test --filter` expression for the classes named like the changed test files).
- **The missing-symbol patterns for Vitest, Jest, javac through Maven, Go, the C# compiler, PHPUnit and RSpec were checked against real messages**; the captured reports and messages are in `tests/data/polyglot/` and the unit tests read them. Kotlin, Swift and TypeScript's own compiler are still unchecked.
- **A clearer base detail for compile errors**: when the runner wrote no report, the per-test line shows the compiler line that names the missing symbol, not the first line of the build output.
- **The note "also passes on the base"** now also finds tests whose report names the class (Maven, .NET) rather than the file.
- **`ok-unproven` is a warning annotation on GitHub Actions**, not a notice: the change passed without proof, and a reviewer should read the assertions.
- **Documented, not changed:** the built-in probe is still for Python only. Outside Python a change that adds a function passes as `ok-unproven` whether its test checks the function or only calls it, or stops in both cases with `base_error_policy: "stop"`. PHPUnit's `--fail-on-risky` and Vitest's `--expect.requireAssertions` stop a new test that makes no assertion at all (run).
- **Gradle, Kotlin and Swift, added the same day** (runs 44343395672 and 44345735856, 28 guard runs each, all as expected): Java with Gradle 9.9.1 and JUnit 5, Kotlin 2.4.21 through Gradle with kotlin.test, and Swift 6.4.2 packages on Linux with `swift test`, once with XCTest and once with Swift Testing. The guard needed no new parser: Gradle writes JUnit XML, and `swift test --parallel --xunit-output` writes one xUnit file for XCTest and one for Swift Testing, which the guard reads as one folder. The real messages `cannot find symbol` (javac through Gradle), `Unresolved reference 'formatPrice'` (Kotlin 2.x) and `type 'Pricing' has no member 'formatPrice'` (Swift) were classified as new code by the existing patterns. Two changes: the new placeholder `{names_regex}` (the test file names as one regular expression, for `swift test --filter`), and the colour codes the Swift compiler writes even without a terminal are taken out of the per-test detail line. Xcode projects, `xcodebuild` and macOS runners were not run.
- **pytest on a hosted runner** (run 44352029536): a pytest fixture in `tests/polyglot/pytest/` ran with pytest 9.2.0 on Python 3.14.10 on GitHub's hosted Linux runner, 7 of 7 guard runs as expected. The built-in probe judged the new-function cases: a test that only calls the new function was STOPPED (`probe-passes`) and a test that checks its result PASSED (`ok-new-code`), also with `base_error_policy: "stop"`. Nothing in the guard needed to change. `tests/polyglot/run_polyglot.py` now takes a fixture's `overrides` for the expected result of a case.
- **The action's `blocks` output follows the guard's exit code** (`action.yml`): the outputs are read from a result file that test code which outlives the guard could change, so `blocks` is now set from the exit code and the action warns when the file disagrees. The outputs are for information; the check passes or fails on the exit code. Tested in `tests/test_ci_files.py` by running the action's step with a stand-in guard.
- **`ci/github-actions.yml`**: the skip step writes the reason to `$GITHUB_ENV` with a random delimiter, as `action.yml` does, instead of the fixed `CG_EOF`, so a reason line cannot end the value early (tested in `tests/test_ci_files.py`).
- **Documentation:** `docs/github-action.md` warns never to use the action as `uses: ./` in the repository it checks, and says the outputs are for information; `docs/ci-platforms.md` records the action's green self-test runs.
- `.github/workflows/polyglot.yml`: one job per ecosystem, each with its official setup action, building the fixture and checking every case. `tests/polyglot/run_polyglot.py` builds a fixture and runs its cases, also locally.
- `VERSION` in `change_guard.py` set to `0.3.0`. 143 unit tests (21 new in `tests/test_polyglot_reports.py`, built on output captured from the runners, and 4 in `tests/test_ci_files.py`); `seed_cases.py` unchanged, 47 cases and 57 guard runs per round, all as expected.

## 0.2.2 (internal 2.2.0), 18 November 2026: first public version

Packaging for the first public release:

- `action.yml`: the guard as a composite action for GitHub Actions, with inputs for the configuration file, the mode, the base and head commits, the skip label and the enforce label. It runs the guard from the action's own files at the pinned version, never from the pull request, uses no other action inside it, writes the step summary and keeps the log line. See [docs/github-action.md](docs/github-action.md).
- `.github/workflows/action-selftest.yml`: runs the action from this repository (`uses: ./`) on a small fixture in `tests/fixtures/action-selftest/` on every push and pull request.
- `VERSION` in `change_guard.py` set to `0.2.2` (it read `2.2.0`). Nothing else in the guard's logic changed.

Hardening after a separate verification round of 0.2.1 found routes that still let a gamed change through.

- The repository's git setup is off limits (V3a). Every git command of the guard runs with hooks switched off and without the user's or the system's git configuration. All worktrees are made before the first test runs. A run in which the tests change the repository's hooks, git configuration or `info` folder ends as ERROR `tampered`, and the change is put back.
- The worktrees are checked before each base and probe run (V3b): the commit, the files the guard wrote, and no file added, changed or removed since. This narrows the route, it does not close it: a process started by the head run that writes into the other worktrees as soon as it is up still wins.
- The worktrees look alike (V4, the cheap form). The guard commits its own changes inside each worktree with one neutral message, so `git status` is clean in all three and `git log -1` does not name the phase.
- Whitespace is exempt in Python files only (V5), and only when the syntax tree is the same.
- A broken configuration on the target branch can be repaired (V7): the skip step works even then and is logged with the note `config-broken`, and a change whose only file is the configuration passes as EXEMPT `config-repair` when its own copy loads.
- Two fixes from a second separate verification round (K08): a Python script whose `#!` line got a carriage return or a trailing space is no longer exempt as whitespace-only, and a `.git/config` that the tests made unreadable is now put back.
- The GitHub Actions example now names version 7 of `actions/checkout` and `actions/upload-artifact`, after the first run on GitHub showed version 4 as deprecated.
- 118 unit tests; `seed_cases.py` has 47 cases and 57 guard runs per round.
- Still documented limits, not fixed: V3b in full, V6, and the rest of R7.

## 0.2.1 (internal 2.1.0), 18 November 2026

Fixes for the 20 defects of a code review of 0.2.0 and the 4 found by the first run with pytest, then three small fixes from a separate verification round.

- The change no longer chooses its own judge (R1): the configuration is read from the base commit, and the CI files take the guard and its reporter from the base and run them from outside the checkout. Only the pull request that installs the guard uses its own copy, and says so.
- Shortcuts closed (R2, R3, R4): the whitespace exemption needs the same Python syntax tree; a generated-code marker counts only when the base already has it; other file types in a change no longer turn the Python probe off.
- The probe sees more and breaks less (R5, R7, R8, R10 to R13): renamed files are compared with their old path; functions inside compound statements, duplicate definitions, lambdas and widened signatures are probed; stub bodies are left alone; a function used at import time counts as noticed; one-line functions, non-ASCII text, bodies on the signature's closing line, form feeds and other encodings are rewritten correctly.
- Every run ends with a verdict (R6, R14, R19): a test that leaves a process running no longer holds the guard past its budget; an unexpected error ends as ERROR `internal` with a log line; a shallow clone is named as such.
- The tests see less (R9, R15, R16, R17): they are not told which commit they run on, they get a reduced environment without CI tokens and control files (new key `pass_env`), a run that changes the log, the guard's scripts or the CI control files ends as ERROR `tampered`, `report_path` must stay inside the worktree, and placeholders are filled in one pass. R15 is closed only in part, by nature: the tests still run as the same user.
- Smaller fixes (R18, R20, P1 to P4): paths with spaces or non-ASCII characters keep their diff, a renamed test file is not reported as deleted, and pytest's exit 5, collection errors, exceptions and error lines are read correctly. The recommended pytest command now carries `--continue-on-collection-errors`.
- New key `guard_files`: a change to the guard's own files gets the note `guard-changed`.
- Verification fixes (K04): a decorator alone no longer makes a stub, an absolute `--config` path through a symbolic link is still read from the base, and a head failure names `pass_env` in its hint.
- 97 unit tests; `seed_cases.py` has 38 cases and 48 guard runs per round.

## 0.2.0 (internal 2.0.0), 17 November 2026

The version that reads per-test results instead of exit codes alone.

- Per-test results: the guard reads the test runner's own report (`report_format`: `unittest-json`, `junit-xml`, `go-json`, `jest-json`, `rspec-json`) and classifies each changed test's result on the base.
- The link to the change: a base error counts as "new code is missing" only when it names something the change adds.
- The neutral-body probe for Python, with its own time box, or your own mutation tool through `probe_command`.
- A second base run and one head retry, so a flaky test is named as such.
- Automatic exemptions for whitespace-only changes, pure renames and generated files.
- Notes on the test diff: assertions removed, tests deleted, skip markers added, snapshots changed, the new code mocked, new tests that also pass on the base.
- The optional edited-tests check (`check_edited_tests`).
- `cg_unittest_report.py`, the per-test reporter for Python unittest.
- Log format `cg2`: the 14 columns of `cg1` plus five.
- 44 unit tests; `seed_cases.py` has 26 seeded and edge cases.

## 0.1.0 (internal 1), 17 November 2026

The first prototype.

- The rule: a change to protected paths must bring a new or changed test that fails on the base commit and passes on the head, judged on exit codes.
- Exempt patterns, the recorded skip step (who and why), a time budget, report-only and blocking modes.
- One log line per run in the 14-column `cg1` format.
- Example CI files for GitHub Actions, GitLab CI, Jenkins and Azure DevOps.
- `seed_cases.py` with five basic seeded cases, four edge checks and a series of ten normal changes.

## Review items

- **R1 to R20:** code review of 0.2.0. R1 configuration and scripts taken from the change; R2 whitespace exemption too broad; R3 a generated-code marker added by the change itself; R4 other file types turned the Python probe off; R5 renamed files not compared with their old path; R6 leftover processes held the guard; R7 definitions inside compound statements and lambdas not probed; R8 new parameters not probed; R9 tests could read which commit they ran on; R10 form feeds shifted the probe rewrite; R11 stub bodies were probed; R12 functions used at import time; R13 one-line, non-ASCII and CRLF sources broke the rewrite; R14 unexpected errors ended without a verdict; R15 the tests' reach into the job's environment; R16 `report_path` outside the worktree; R17 placeholders filled in more than one pass; R18 paths with spaces or non-ASCII characters lost their diff; R19 a shallow clone was not named; R20 a renamed test file was reported as deleted.
- **P1 to P4:** first run with pytest. P1 exit 5 with an empty report read as a failing test; P2 one collection error hid the other test files' results; P3 pytest writes exceptions as failures without a type; P4 the cause sentence did not name the error line.
- **K04:** first separate verification round, of 0.2.1: three small fixes (stubs and decorators, `--config` through a symbolic link, the `pass_env` hint).
- **V3a to V7:** findings of that verification. V3a hooks and git configuration planted by the tests; V3b a process that patches the other worktrees; V4 tests that tell the phases apart through git; V5 whitespace exemption outside Python; V6 a change that adds one parameter and removes another passes as `ok-unproven` (documented limit); V7 a broken configuration on the target branch could not be repaired.
- **K08:** second separate verification round, of 0.2.2: two fixes (the `#!` line and an unreadable `.git/config`).
