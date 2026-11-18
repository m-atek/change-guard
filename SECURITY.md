# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting instead (the "Report a vulnerability" button under the Security tab of this repository), with:

- what an attacker can do, and what they need for it (for example: write access to a pull request branch, a label permission, control of the test code);
- the version of the guard (`change_guard.py --version`), git, Python and the CI platform;
- the smallest repository, configuration or script that shows it.

You will get an answer as soon as the maintainer can give one. This is a project maintained by one person on a best-effort basis, so there is no guaranteed response time. Once a fix is out, the report is credited in the changelog unless you ask otherwise.

## What the guard is, and is not

The guard runs the pull request's own tests on the build agent, as the same user as the guard itself. Treat everything those tests do as code from the pull request author.

- **Give the guard's job no secrets.** No deployment keys, no cloud credentials, no tokens with write access. Keep the read-only token of the example workflow, keep the `pull_request` trigger (never `pull_request_target`), bind no Jenkins credentials to pull request builds, and keep Azure DevOps' "Make secrets available to builds of forks" off. Any variable you name in `pass_env` reaches the tests.
- **It is not a security boundary.** Test code written on purpose to attack the guard can still get a change through, for example with a background process that changes the guard's working copies after the guard has checked them. The guard catches several such attempts and ends the run as ERROR `tampered`, but it does not isolate the tests. If you need that, run each test run in its own container or under a user account that cannot write to the guard's folders.
- **The tests can read what the job's user can read** on the agent, and a process they start can outlive the job on a long-lived agent. Use fresh, disposable agents for pull request builds where you can.
- **With the action** (`action.yml`), pin it to the full commit hash of a release. The action refuses the `pull_request_target` trigger, runs the guard from its own files at that commit and never from the pull request, and uses no other action inside it. Its only network call is one read of the pull request's label history with the job token, when the skip label is present.
- **The pipeline file comes from the pull request** on every supported platform. Protect the pipeline file, `tools/change-guard/` and `change-guard.json` with code owner review.

Reports that show a way around the guard's own checks (configuration from the base, the tamper checks, the hidden phase, the probe) are welcome even when they fall under the known limits in the README; they help keep that list honest.
