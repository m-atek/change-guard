# Polyglot fixtures

Demo projects, no real data. `.github/workflows/polyglot.yml` runs `run_polyglot.py` on each folder here, one job per ecosystem on GitHub's hosted Linux runner. [docs/languages.md](../../docs/languages.md) has the results.

| Folder | Language and runner |
|---|---|
| `vitest/` | TypeScript, Vitest |
| `jest/` | JavaScript (CommonJS), Jest |
| `maven/` | Java 21, Maven, JUnit 5 |
| `go/` | Go, `go test` |
| `dotnet/` | C#, .NET, xUnit |
| `phpunit/` | PHP, PHPUnit through Composer |
| `rspec/` | Ruby, RSpec through Bundler |
| `gradle/` | Java 21, Gradle, JUnit 5 |
| `kotlin/` | Kotlin on the JVM, Gradle, kotlin.test on JUnit 5 |
| `swift/` | Swift Package Manager, XCTest |
| `swift-testing/` | Swift Package Manager, Swift Testing |

Each folder holds:

- `base/`: the main branch, a tiny shop with one function (`total`), its test and a `change-guard.json` for that runner. `base/gitignore` becomes `.gitignore`.
- `changes/<case>/`: the files each seeded change lays over main, one branch per folder: `1-no-test`, `2-test-passes-on-base`, `3-real-test`, `4-new-function-call-only`, `5-new-function-real-test`.
- `fixture.json`: the `prepare` command that installs the dependencies once before the base commit (and writes the lock file where the runner has one), and any extra variants for that runner.

`run_polyglot.py` holds the expected result and cause of every case. The bulk-discount tests carry the word "bulk" in their names and the new-function tests the word "format", which is how the script finds the new tests in the guard's per-test results; keep that when you edit a fixture.

Run one locally where its toolchain is installed (it builds a throwaway repository in the folder you name and pushes nothing):

```
python3 tests/polyglot/run_polyglot.py go "$TMPDIR/cg-go" --prepare
```

The folder has no `__init__.py` and no file named `test*.py`, so `python3 -m unittest discover -s tests` does not collect anything from it.
