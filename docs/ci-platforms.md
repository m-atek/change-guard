# CI platforms

The folder `ci/` holds one example file per platform, and `action.yml` at the root packages the GitHub Actions route as an action. All of them run the same script and differ only in how they find the base, the head, the mode and the skip.

**Only the GitHub Actions route has actually run on its platform, and the workflow file in `ci/` only in an earlier version.** The GitLab, Jenkins and Azure DevOps files were written from general knowledge of those platforms and have never run there. Treat them as a starting point and run them on a branch before you depend on them.

| File | Platform | Has it run there? |
|---|---|---|
| `ci/github-actions.yml` | GitHub Actions, pull request check | An earlier version, on 18 November 2026 (see below); the current version, with the 0.3.1 order of the steps, has not run there |
| `action.yml` | GitHub Actions, the same check packaged as an action ([github-action.md](github-action.md)) | Its self-test, `.github/workflows/action-selftest.yml`, which runs the action from the checkout (`uses: ./`) on the fixture in `tests/fixtures/action-selftest/`, has run green on GitHub's hosted Linux runner on 18 November 2026, in private repositories, for versions up to 0.3.1. Since 0.3.1 it also checks that a hostile `json.py` and `sitecustomize.py` in the checkout do not run inside the action, and since 0.3.2 that a `working-directory` inside the checkout is refused and that the `mode` input ignores case and spaces; versions 0.3.2 and 0.3.3 ran green with all seven cases on 19 November 2026 in this repository's own workflows on GitHub's hosted Linux runner. The workflows repeat it for every later commit. On 23 November 2026 it ran in a separate private repository on real pull request events, with the workflow of the quick start and the default base, head and token, first from a copy of the action in that repository and then by name and full commit hash (at the commit before the release commit of v0.3.3, with the same action files). The three seeded cases gave STOPPED (no-test), STOPPED (test-passes-on-base) and PASSED (ok); report mode stayed green, the enforce label turned the check red, a skip without a reason was refused, and a skip with a reason passed as SKIPPED and recorded the account that set the label. Not yet listed on the Marketplace, and not yet run on pull requests from forks |
| `ci/gitlab-ci.yml` | GitLab CI, merge request job | No |
| `ci/Jenkinsfile.change-guard` | Jenkins multibranch pipeline with pull request discovery | No |
| `ci/azure-pipelines.change-guard.yml` | Azure DevOps Pipelines, build validation | No |

## What all four do the same way

- **The pull request does not choose its own judge.** Before the guard runs, a few shell lines take `change_guard.py` and `cg_unittest_report.py` from the base commit with `git show`, put them in a temporary folder outside the checkout, and run the guard from there. The guard reads `change-guard.json` from the base commit too. Only when the base has no copy yet (the pull request that installs the guard) does the job use the pull request's own files, and it prints a warning that says so. Keep both scripts in `tools/change-guard/` on the target branch.
- **The pipeline file itself still comes from the change** on every platform, at least for trusted contributors, so a pull request can edit the job that runs the guard. Protect the pipeline file, `tools/change-guard/` and `change-guard.json` with a CODEOWNERS rule (or the platform's required reviewers for paths) and require code owner review in the branch rules.
- **No secrets.** The guard runs the pull request's own tests on the build agent. Give the job no secrets and no write access.
- **Full history.** The guard needs the merge base, so a shallow clone ends as ERROR `git` with a hint.
- **Report-only by default,** with one setting, `CHANGE_GUARD_MODE=block`, to make it blocking.

## GitHub Actions (`ci/github-actions.yml`)

Copy it to `.github/workflows/change-guard.yml`. It triggers on pull request events (opened, synchronize, reopened, labeled, unlabeled, edited) with a read-only token, checks out with full history, and passes the pull request's base and head commits.

- **Mode:** the repository variable `CHANGE_GUARD_MODE=block` makes it blocking. The label `change-guard-enforce` puts one pull request in blocking mode; it can only make the guard stricter.
- **Required check:** make the job `change-guard` a required status check in the branch rules. In report-only mode it is always green, so this is safe from the start.
- **Skip:** the label `change-guard-skip` plus a line `Change-Guard-Skip-Reason: ...` in the pull request description. The job reads who added the label from the pull request's event history. A label without a reason is refused, and if the labeller cannot be read the guard fails closed.
- **Log:** the log line goes into the step summary and into an artifact kept for 90 days.
- **Order of the steps (0.3.1, finding I8 of the 0.3.0 audit):** the checkout keeps no token on disk (`persist-credentials: false`); the guard is taken from the base branch straight after the checkout and its hash goes into a step output, which the guard step checks again; the skip values go from the skip step's outputs into the guard step's own `env:`, never through `GITHUB_ENV`. Your set-up steps come after these. A set-up step such as `npm ci` or `pip install -e .` still runs the pull request's code with the whole job environment; use `setup_command` in the configuration where you can. The 0.3.1 and later versions of this file have not run on GitHub yet; the earlier one did (below).
- **Trigger:** keep `pull_request`. Do not change it to `pull_request_target`: the guard runs the pull request's own test code, and that trigger runs it with access to the repository's secrets and a token that can write.
- **Action versions:** the file names `actions/checkout@v7` and `actions/upload-artifact@v7`. Pin them to a commit if your policy asks for that.

### What the first run on GitHub showed (18 November 2026)

The workflow ran in a private demonstration repository built with `seed_cases.py --export`, on GitHub's hosted Linux runner (image ubuntu-26.04, git 2.56.1, Python 3.14.4).

- Pull request 1 (no test) ended STOPPED (`no-test`), pull request 2 (a test that also passes without the change) ended STOPPED (`test-passes-on-base`) and pull request 3 (a test that checks the change) ended PASSED (`ok`), each with the same sentence as in a local run.
- The skip label with a reason line ended SKIPPED, and the kept log line names who set the label and the reason. The label without a reason was refused (STOPPED, `skip-no-reason`).
- In report mode the check stayed green while the result line said STOPPED; the enforce label turned the same pull request red.
- After the main branch moved by one commit, the results did not change; the guard printed the merge base it used.
- The 118 unit tests of that version and a full round of seeded cases passed on the same runner under Python 3.10.22, 3.11.18, 3.12.16, 3.13.18, 3.14.4 and 3.14.10. In the pull request runs the guard itself took under 0.2 seconds and a whole job 6 to 14 seconds.
- An earlier version of the workflow named version 4 of `actions/checkout` and `actions/upload-artifact`, which GitHub marks as deprecated; with version 7 the runs showed no warning and still kept the log artifact.
- On GitHub's free plan a private repository cannot make a status check required (GitHub answered "Upgrade to GitHub Pro or make this repository public to enable this feature"), so the pull requests there turned red but merging was not blocked. Public repositories and paid plans can require the check.
- Three runs started right after the workflow file changed on the main branch still ran the earlier version of the workflow file. The guard's own result was right in each. The likely cause, not confirmed, is that GitHub had not rebuilt the pull request's merge commit yet.

Not covered by that run: pytest on a hosted runner (it ran later, in the polyglot workflow, in a private repository), Windows and macOS runners, pull requests from forks, a blocked merge, and real project code.

## GitLab CI (`ci/gitlab-ci.yml`), not run on GitLab

A merge request job with full history (`GIT_DEPTH: "0"`), base the tip of the target branch (fetched; before 0.3.1 it was `CI_MERGE_REQUEST_DIFF_BASE_SHA`, the merge base, so a branch cut before the guard was installed brought its own guard and rules), head `CI_COMMIT_SHA`. The project variable `CHANGE_GUARD_MODE=block` makes it blocking, and "Pipelines must succeed" makes it required. Skip: the merge request label `change-guard-skip` plus the same reason line in the description, then run the pipeline again, since a label change alone does not start one. To record who added the label, give the job a project access token with `read_api` scope in the masked variable `CHANGE_GUARD_API_TOKEN`; without it, the job records the user who started the pipeline and marks it "(pipeline user)". The guard does not hand that token to the tests, and the job unsets it before the guard starts; but any token the job holds, GitLab's own `CI_JOB_TOKEN` included, can be read by the tests from a parent process, so give it the smallest scope or leave it out. Check on your GitLab version that `CI_MERGE_REQUEST_DESCRIPTION` is filled.

## Jenkins (`ci/Jenkinsfile.change-guard`), not run on Jenkins

One stage that runs only for change requests (multibranch pipeline with pull request discovery), fetches the target branch and full history, and runs the guard against `origin/<target>`. The mode comes from a global or folder variable `CHANGE_GUARD_MODE`. Skip: rebuild with the parameter `CHANGE_GUARD_SKIP_REASON`; who skipped is the user who started that build. A build that no person started (a timer, a push, an upstream job) gives no name, and since 0.3.2 the guard then refuses the skip (STOPPED `skip-no-who`); before, the file filled in the name "unknown" and the skip passed. Turn off shallow clone in the checkout behaviours, bind no credentials to pull request builds, and check on first use that the script sandbox allows `currentBuild.getBuildCauses`.

## Azure DevOps (`ci/azure-pipelines.change-guard.yml`), not run on Azure DevOps

A job that runs for pull request builds, made required as a build validation in the branch policy. The pipeline variable `CHANGE_GUARD_MODE=block` makes it blocking. Skip: queue the build again with the queue-time variable `CHANGE_GUARD_SKIP_REASON`; who skipped is `Build.RequestedFor`. Keep "Make secrets available to builds of forks" off.

## Time limits

A run costs about twice the time of the changed tests, plus one run per added function (an estimate). Check the job's timeout on your first run (`timeout-minutes: 15` in the GitHub workflow).
