# Edge cases: how the change guard handles attempts to game it

The rule is simple: a change to the protected paths must bring a test that fails on the base commit and passes on the change. The base commit is the merge base with your target branch, the code the change was written against. If the target branch has moved since, your normal test job covers that.

The obvious way to game the rule is a new test that fails on the base only because the function it calls does not exist there yet, and asserts nothing useful. This page describes how the guard handles that and the other cheap routes, and what it cannot handle.

## What the guard reads

Not the exit code alone. It reads the test runner's own per-test report and puts each changed test's result on the base commit in one class: failed by assertion, errored because a name the change adds is missing, errored while loading for another reason, passed, skipped, or not collected. A missing name counts as "new code" only when it is a name the change itself adds; when the error text names a missing name the guard cannot link to the change (a dictionary key, an attribute), that is never proof either (since 0.3.1 it ends as `ok-unproven` when it is raised inside a test). An exception whose text names no missing name is behaviour and counts as proof (`errored_counts_as_proof`), so a test that asserts nothing can still pass as `ok` when the old code raises such an exception (for example `RATES.get('de').bit_length()` on a base where the key is missing raises `AttributeError` on `None`). A base that cannot load the tests for a reason the guard cannot link to the change ends as an error with its cause. Files the change adds outside the protected paths are laid over the base with the tests; a file it edits there is laid over only when it is test material (since 0.3.2, see [how-it-works.md](how-it-works.md)), so the old code keeps its own helpers and data files. A load error caused by an added file, or by an edited file that is not test material, is still possible.

## Compiled languages

In Go, a test that calls a function the base lacks breaks the build of the whole package on the base, so the guard links every test in that package to that one build error. In a Maven build, a test that does not compile stops every test and leaves no Surefire report, and `dotnet test` writes no TRX file; in a Gradle build, a test that does not compile leaves no report; the guard then reads the end of the output as one load error, so "cannot find symbol" can still be linked to a name the change adds. Either way, an error that names something the change adds counts as new code, not as proof.

Since version 0.3.0 the readers and the compiler-message patterns for Go, Maven and Gradle with javac, Kotlin through Gradle, the C# compiler through `dotnet test`, Vitest, Jest, PHPUnit, RSpec and Swift packages with `swift test` have run on real builds on GitHub's hosted Linux runner, on demonstration projects ([languages.md](languages.md)); Xcode projects on macOS were not run. Check the patterns against one real error from your own runner before you rely on them; you can add your own with `missing_symbol_patterns`.

## The probe

A base failure that only says "the new function is missing" proves nothing, so the guard runs one more check on the head. Each function the change adds, or gives a new parameter, keeps its name and signature, its body becomes `return None`, and the changed tests run again. For every such function at least one test must stop passing, or the change is stopped.

That catches a test that only calls the new code, a test that mocks it, and a test that only checks that it exists, while a real test of the new code passes. The probe covers functions the change adds or widens, not changed bodies; for a changed body, the run on the base commit does that job.

The probe is built in for Python only. For other languages it can call your own mutation tool (`probe_command`), which has not yet been tried with a real tool. Without it, the guard says plainly that no probe ran, and it cannot tell a test that only calls a new function from a test that checks it: both pass as `ok-unproven` (on GitHub with a warning annotation), or both stop with `base_error_policy: "stop"`. A runner option that fails a test without assertions (PHPUnit's `--fail-on-risky`, Vitest's `--expect.requireAssertions`) stops the test that asserts nothing at all; [languages.md](languages.md) has the runs.

## The other cheap routes

- **Skip and expected-failure markers:** a change whose only new test is marked as skipped or as an expected failure is stopped (`no-test-ran`), and a marker added in the diff gets a note.
- **A flaky test:** the base runs twice before anything passes, and different results stop the change (`flaky-on-base`).
- **A weakened existing test next to one honest new test:** removed assertion lines get a note. As an option (`check_edited_tests`), the old version of the edited test runs on the new code; if it fails there, the change is stopped. A test written to lie can still get past that option.
- **Refactors:** a change that only renames or moves a file without changing its content, or only changes whitespace in a Python file whose syntax tree and first line stay the same, is exempt and logged, so nobody needs a fake test to get one through. Any other refactor, a renamed function included, goes through the recorded skip step.
- **Cheap phase signals:** the guard removes the signals that tell a test for free which commit it runs on. The phase variable goes to the setup command only, folders and report files have random names of one shape (before 0.3.1 the report files were numbered in run order, so the head run could be recognised), each run's report sits alone in a new folder that is removed after it is read (since 0.3.2; before, a test could count the earlier reports next to its own), and the guard commits its own changes in each worktree with the same neutral message, so `git status` and `git log -1` look alike in all of them. This does not mean a test cannot tell the runs apart: a test can always look at the code it runs against. That belongs to "It is not a security boundary" below.
- **Tampering:** a run in which the tests change the log, the summary file, the guard's own scripts, the CI platform's control files, or the repository's hooks, git configuration or `info` folder ends as ERROR `tampered`, and what they changed in the repository's `.git` is put back. Before each base and probe run, the guard also checks that the worktree still holds exactly what it put there.
- **Loosening the rules:** the configuration is read from the base commit, so a pull request cannot loosen the rules it is judged by. It gets the note `guard-changed`.

## What has been tested

All of this was tested on a small demonstration project, not on a production codebase: 47 seeded, edge and library cases plus ten normal changes, run in several rounds with one log line for every run. Both basic bad cases and all 23 gaming cases were stopped each time, all 11 honest changes passed each time, and none of the ten normal changes was stopped. At version 0.3.2, 245 unit tests pass (`tests/`). Per-test reports came from Python unittest and pytest and, since version 0.3.0, from Vitest, Jest, Maven Surefire, Gradle, `go test`, `dotnet test`, PHPUnit, RSpec and `swift test` (XCTest and Swift Testing) on GitHub's hosted Linux runner, on demonstration projects ([languages.md](languages.md)). On GitHub Actions the three basic cases, the skip label, report-only mode and the enforce label behaved as they do locally; no other CI platform has run the guard. The README's "How it was tested" section has the full numbers.

On that tiny suite the guard took about half a second per run with unittest and under a second with pytest, which says nothing about your suite. In a real pipeline, expect roughly twice the time of the changed tests, plus one run per added function; that is an estimate, not a measurement.

## What it cannot do

- **It does not judge the assertion.** It shows that a test depends on the change. It never shows that the assertion checks the right behaviour: a test that asserts the wrong value passes. Someone still reads the assertions.
- **It is not a security boundary.** The tests of a change run on the same build agent as the guard, with the same rights, so test code written on purpose to attack it can still get a change through, for example by starting a background process that alters the guard's working copies after the guard has checked them. In a separate verification round such a process got a gamed change through ten runs out of ten. The guard catches several such attempts and ends the run as tampered, and a reviewer who reads the test code would see one. Closing that route fully needs the test runs isolated from the guard, each in its own container or under a user account that cannot write to the guard's folders; the guard does not do that by itself.
- **Test code written to lie can still tell the runs apart** through `git log -1 --stat`, `git log --skip=1`, `HEAD~1`, or a counter kept outside the worktrees, and it can rewrite its own report after the runner wrote it.
- **Without a probe for your language**, a test that only calls new code passes with a note for the reviewer (`ok-unproven`), unless you set `base_error_policy` to `stop`, which also stops honest changes.
- **Until you switch it to blocking**, it runs in report-only mode; blocking is one setting.

Do not describe the guard as impossible to game. It catches lazy and mistaken tests, and several deliberate tricks; a person who reads the tests catches the rest.
