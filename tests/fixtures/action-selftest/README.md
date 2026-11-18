# Fixture for the action self-test

Demo project, no real data. `.github/workflows/action-selftest.yml` runs `build.sh`, which turns these files into a throwaway git repository under `$RUNNER_TEMP`, and then runs the action from this repository (`uses: ./`) on it.

- `base/` is the main branch: a tiny shop module (`src/pricing.py`), its unittest suite and a `change-guard.json` that protects `src/`. `base/gitignore` becomes `.gitignore`.
- `changes/1-no-test/`: a bulk discount with no test. Expected: STOPPED (`no-test`).
- `changes/2-test-passes-on-base/`: the same discount with a test that also passes without it. Expected: STOPPED (`test-passes-on-base`).
- `changes/3-real-test/`: the same discount with a test that checks it. Expected: PASSED (`ok`).

The files are the seeded demonstration cases of `seed_cases.py` (`PRICING_V1`, `PRICING_BULK`, `TEST_V1`, `TEST_BULK_WEAK`, `TEST_BULK_GOOD`). Keep them in step if those change. The folder has no `__init__.py`, so `python3 -m unittest discover -s tests` does not collect the fixture's own tests.
