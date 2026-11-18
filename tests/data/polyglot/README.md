# Captured runner output

Demo projects, no real data. Every file here was written by a real test runner on GitHub's hosted Linux runner (image ubuntu-26.04) on 18 November 2026, in run 44335953379 of `.github/workflows/polyglot.yml` with capture switched on (Gradle, Kotlin, Swift and Swift Testing: run 44343395672), for the fixtures in `tests/polyglot/`. `tests/test_polyglot_reports.py` reads them.

File names: `<case>-<phase>.<ext>` is the runner's report for that seeded case, on the head or on the base (the head's test files laid over main); `<case>-base-output.txt` is the end of the runner's output where it wrote no report because the tests did not compile on the base (Maven, .NET).

What was changed in them, and nothing else:

- The worktree folder is shown as `<worktree>`; the tests put a folder back in its place.
- Surefire's `<properties>` block (every Java system property of the runner) is shown as `<properties/>`.
- A `##[error]` that GitHub's log viewer put in front of compiler lines (the problem matchers of `setup-go` and `setup-dotnet`) was taken out.
- The Swift compiler colours its messages even when its output is not a terminal. GitHub's log shows the escape character as the two characters `^[`; the files hold the escape character again, as the compiler wrote it.
- `swift test` writes two files into the report folder, `results.xml` (XCTest) and `results-swift-testing.xml` (Swift Testing); the files here keep those names after the case and phase.

Versions: Vitest 3.2.4 and Jest 29.7.0 on Node.js 24.22, Maven 3.9.15 with Surefire 3.5.2 and JUnit Jupiter 5.11.4 on Temurin 21.0.13, Go 1.27.4, .NET SDK 11.0.100 with xUnit 2.9.3, PHPUnit 11.5.58 on PHP 8.4.27, RSpec 3.13 (rspec-core 3.13.7) on Ruby 3.4.12, Gradle 9.9.1 with JUnit Jupiter 5.11.4 on Java 21.0.13, Kotlin 2.4.21 with kotlin.test through Gradle 9.9.1, Swift 6.4.2 (the runner image's own toolchain) with XCTest and Swift Testing.
