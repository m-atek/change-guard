# Contributing

Thank you for taking the time. This project is maintained by one person on a best-effort basis: issues and pull requests are read, but there is no guaranteed response time, and changes that widen the scope a lot may be declined to keep the tool small.

## Running the tests

You need git and Python 3.9 or later; nothing to install.

```
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 python3 -B seed_cases.py
```

The first runs the unit tests (139 at version 0.3.0). The second builds a throwaway repository in a temporary folder, runs the guard on every seeded case and on ten normal changes, prints a table, and ends with `overall: ALL CHECKS AS EXPECTED` when everything behaved as expected. It removes the folder afterwards (`--keep` keeps it). Both must pass before a pull request is merged; `.github/workflows/selftest.yml` runs them on Python 3.10 to 3.14. A change to `action.yml` must also keep `.github/workflows/action-selftest.yml` green: it runs the action from the checkout (`uses: ./`) on the fixture in `tests/fixtures/action-selftest/`. A change to how the guard runs or reads a test runner must keep `.github/workflows/polyglot.yml` green: it runs the guard on the fixtures in `tests/polyglot/` with Vitest, Jest, Maven, Gradle, Kotlin, Go, .NET, PHPUnit, RSpec and Swift (`python3 tests/polyglot/run_polyglot.py <folder> <new folder> --prepare` runs one of them where that toolchain is installed).

A change to the guard's behaviour needs a unit test that fails without the change and passes with it, which is the rule the guard itself applies. A new way around the guard is best added as a seeded case in `seed_cases.py`.

## A good bug report

- The full output of the guard, from the `change-guard 0.3.0 | mode ...` line to the `log: ...` line, and the log line itself.
- Your `change-guard.json` (remove anything private).
- The versions of the guard, git and Python, the operating system, and the CI platform.
- What you expected to happen, and why.
- If you can, the smallest repository or script that reproduces it: a base commit, a head commit, and the command you ran.

For a security problem, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Style

Python 3 standard library only, no dependencies. Messages are one plain sentence that names the cause. Keep the code readable for someone who reviews it before trusting it in their pipeline.
