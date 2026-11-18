#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Builds one polyglot fixture into a throwaway git repository and runs the guard on its seeded cases.

Demo project, no real data. Nothing is pushed. Standard library only.

    python3 tests/polyglot/run_polyglot.py ECOSYSTEM WORK_FOLDER [--prepare] [--summary FILE] [--capture]

ECOSYSTEM is a folder next to this script (vitest, jest, maven, go, dotnet,
phpunit, rspec). The script:

1. copies ECOSYSTEM/base/ into WORK_FOLDER/repo (base/gitignore becomes
   .gitignore) and, with --prepare, runs the fixture's "prepare" command there
   first (it installs the dependencies once and writes the lock file, which
   becomes part of the base commit);
2. commits it as main, and every folder in ECOSYSTEM/changes/ as one branch
   from main whose one commit lays those files over main;
3. runs change_guard.py in blocking mode on every branch, and on the variants
   (the same branch with a configuration read from disk: VARIANTS below for
   every fixture, plus the "variants" of the fixture's fixture.json),
   and checks the result, the cause, the notes and the class of each new test
   on the base against the expectations below;
4. prints one line per case, writes a Markdown table to --summary (for
   example $GITHUB_STEP_SUMMARY) and exits 1 when any case differs.

With --capture it also runs the test command itself on the head and on the
base (the head's test files laid over main) of every case, and prints the
runner's own report and output between BEGIN and END lines, so real reports
can be copied into the unit tests.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, KIT)

import change_guard as cg  # noqa: E402

IDENTITY = {
    "GIT_AUTHOR_NAME": "Demo Engineer", "GIT_AUTHOR_EMAIL": "demo@example.invalid",
    "GIT_COMMITTER_NAME": "Demo Engineer", "GIT_COMMITTER_EMAIL": "demo@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}

# The seeded cases every fixture has, with what the guard must answer.
# "new_test_class" is the class each new test of the case must get on the base;
# it shows how the guard read the runner's real message. A new test is a test
# whose id holds the case's marker word: every fixture names its bulk-discount
# tests with "bulk" and its new-function tests with "format", and no test of
# the base holds either word.
CASES = [
    {"branch": "1-no-test", "title": "Bulk discount, no test",
     "expect": ("STOPPED", "no-test")},
    {"branch": "2-test-passes-on-base", "title": "Bulk discount with a test that also passes without it",
     "expect": ("STOPPED", "test-passes-on-base"), "new_test_class": "passed", "marker": "bulk"},
    {"branch": "3-real-test", "title": "Bulk discount with a test that checks it",
     "expect": ("PASSED", "ok"), "new_test_class": "failed-assertion", "some": True, "marker": "bulk"},
    {"branch": "4-new-function-call-only", "title": "New function with a test that only calls it",
     "expect": ("PASSED", "ok-unproven"), "new_test_class": "errored-new-symbol", "notes": ["probe-unavailable"],
     "probe": "unavailable", "marker": "format"},
    {"branch": "5-new-function-real-test", "title": "New function with a test that checks its result",
     "expect": ("PASSED", "ok-unproven"), "new_test_class": "errored-new-symbol", "notes": ["probe-unavailable"],
     "probe": "unavailable", "marker": "format"},
]
# The same two new-function cases with base_error_policy "stop", read from disk.
VARIANTS = [
    {"branch": "4-new-function-call-only", "name": "4-new-function-call-only, policy stop",
     "config": {"base_error_policy": "stop"}, "expect": ("STOPPED", "base-error-only")},
    {"branch": "5-new-function-real-test", "name": "5-new-function-real-test, policy stop",
     "config": {"base_error_policy": "stop"}, "expect": ("STOPPED", "base-error-only")},
]


def sh(command, cwd, env=None, check=True):
    proc = subprocess.run(command, shell=True, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode("utf-8", "replace")
    if check and proc.returncode != 0:
        print(out)
        raise SystemExit("command failed (exit %d): %s" % (proc.returncode, command))
    return proc.returncode, out


def git(repo, *args):
    env = dict(os.environ, **IDENTITY)
    proc = subprocess.run(["git", "-C", repo] + list(args), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise SystemExit("git %s failed: %s" % (" ".join(args), proc.stderr.decode("utf-8", "replace")))
    return proc.stdout.decode("utf-8", "replace").strip()


def copy_tree(src, dst):
    for folder, _, names in os.walk(src):
        rel = os.path.relpath(folder, src)
        for name in names:
            target_name = ".gitignore" if (rel == "." and name == "gitignore") else name
            target = os.path.join(dst, rel, target_name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(folder, name), target)


def build(eco_dir, repo, prepare):
    fixture = load_fixture(eco_dir)
    os.makedirs(repo)
    copy_tree(os.path.join(eco_dir, "base"), repo)
    if prepare and fixture.get("prepare"):
        print("prepare: %s" % fixture["prepare"], flush=True)
        started = time.monotonic()
        _, out = sh(fixture["prepare"], repo)
        print("\n".join(out.rstrip().splitlines()[-15:]))
        print("prepare took %.1f s" % (time.monotonic() - started), flush=True)
    git(repo, "init", "--quiet", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "Demo shop: first version")
    changes = os.path.join(eco_dir, "changes")
    for case in CASES:
        folder = os.path.join(changes, case["branch"])
        if not os.path.isdir(folder):
            raise SystemExit("missing seeded change %s" % folder)
        git(repo, "checkout", "--quiet", "-B", case["branch"], "main")
        copy_tree(folder, repo)
        git(repo, "add", "-A")
        git(repo, "commit", "--quiet", "-m", case["title"])
    git(repo, "checkout", "--quiet", "main")
    return fixture


def load_fixture(eco_dir):
    path = os.path.join(eco_dir, "fixture.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def new_test_files(eco_dir, branch, cfg):
    tests_rx = [cg.glob_to_regex(p) for p in cfg["tests"]]
    folder = os.path.join(eco_dir, "changes", branch)
    found = []
    for root, _, names in os.walk(folder):
        for name in names:
            rel = os.path.relpath(os.path.join(root, name), folder).replace(os.sep, "/")
            if cg.matches_any(rel, tests_rx):
                found.append(rel)
    return sorted(found)


def new_tests(case, classes):
    """The base classes of the case's new tests: the tests whose id holds the case's marker word."""
    marker = case.get("marker") or next((c["marker"] for c in CASES if c["branch"] == case["branch"] and c.get("marker")), "")
    if not marker:
        return {}
    return {t: c for t, c in (classes or {}).items() if marker in t.lower()}


def run_guard(repo, branch, work, label, config=None):
    result = os.path.join(work, "result-%s.json" % re.sub(r"\W+", "-", label))
    cmd = [sys.executable, "-B", os.path.join(KIT, "change_guard.py"), "--repo", repo, "--base", "main",
           "--head", branch, "--mode", "block", "--explain", "--ref", label, "--log", os.path.join(work, "runs.log"),
           "--result-json", result]
    if config:
        cmd += ["--config", config]
    started = time.monotonic()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    secs = time.monotonic() - started
    out = proc.stdout.decode("utf-8", "replace")
    try:
        with open(result, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {"result": "NO-RESULT", "cause": "no-result-json", "classes": {}, "notes": []}
    return proc.returncode, out, data, secs


def check(case, data, files, rc):
    problems = []
    want_result, want_cause = case["expect"]
    if (data.get("result"), data.get("cause")) != (want_result, want_cause):
        problems.append("expected %s (%s), got %s (%s)" % (want_result, want_cause, data.get("result"), data.get("cause")))
    want_rc = 0 if want_result in cg.LETS_THROUGH else (2 if want_result == "ERROR" else 1)
    if rc != want_rc:
        problems.append("exit code %d, expected %d" % (rc, want_rc))
    for note in case.get("notes", []):
        if note not in (data.get("notes") or []):
            problems.append("note %s missing" % note)
    if case.get("probe") and data.get("probe") != case["probe"]:
        problems.append("probe %r, expected %r" % (data.get("probe"), case["probe"]))
    want_class = case.get("new_test_class")
    if want_class and data.get("cause") != "no-test":
        mine = new_tests(case, data.get("classes"))
        if not mine:
            problems.append("no test of %s in the per-test results" % ", ".join(files))
        elif case.get("some"):
            if want_class not in mine.values():
                problems.append("no new test is %s: %s" % (want_class, mine))
        elif set(mine.values()) != {want_class}:
            problems.append("new tests should be %s: %s" % (want_class, mine))
    return problems


def capture(eco, eco_dir, repo, work, cfg):
    """Run the test command itself on head and base of every case and print the runner's report."""
    for case in CASES[1:]:
        files = new_test_files(eco_dir, case["branch"], cfg)
        for phase in ("head", "base"):
            wt = os.path.join(work, "capture-%s-%s" % (case["branch"], phase))
            git(repo, "worktree", "add", "--detach", "--quiet", wt, case["branch"] if phase == "head" else "main")
            if phase == "base":
                for f in files:
                    shutil.copyfile(os.path.join(eco_dir, "changes", case["branch"], f), os.path.join(wt, f))
            report = os.path.join(work, "capture-%s-%s.%s" % (case["branch"], phase, cg.REPORT_FORMATS[cfg["report_format"]]))
            if cfg["report_path"]:
                report = os.path.join(wt, *cfg["report_path"].split("/"))
            if cfg["setup_command"]:
                sh(cfg["setup_command"], wt, check=False)
            command = cg.expand_command(cfg["test_command"], files, report)
            rc, out = sh(command, wt, env=dict(os.environ, CHANGE_GUARD_REPORT=report), check=False)
            tag = "%s %s %s" % (eco, case["branch"], phase)
            print("===== BEGIN output %s (exit %d) =====" % (tag, rc))
            print(out.replace(wt, "<worktree>").rstrip())
            print("===== END output %s =====" % tag)
            paths = []
            if os.path.isdir(report):
                for root, _, names in os.walk(report):
                    paths += [os.path.join(root, n) for n in sorted(names) if n.endswith((".xml", ".trx", ".json"))]
            elif os.path.exists(report):
                paths = [report]
            for path in paths:
                with open(path, encoding="utf-8-sig", errors="replace") as fh:
                    text = fh.read()
                # Surefire copies every system property into its report; they say nothing about the tests.
                text = re.sub(r"<properties>.*?</properties>", "<properties/>", text, flags=re.S)
                text = text.replace(wt, "<worktree>")
                print("===== BEGIN report %s %s =====" % (tag, os.path.basename(path)))
                print(text.rstrip())
                print("===== END report %s =====" % tag)
            git(repo, "worktree", "remove", "--force", wt)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("ecosystem")
    p.add_argument("work")
    p.add_argument("--prepare", action="store_true", help="run the fixture's prepare command before the first commit")
    p.add_argument("--summary", help="append a Markdown summary to this file")
    p.add_argument("--capture", action="store_true", help="also print the runner's own reports for every case")
    args = p.parse_args()
    eco_dir = os.path.join(HERE, args.ecosystem)
    if not os.path.isdir(eco_dir):
        raise SystemExit("no fixture named %s" % args.ecosystem)
    work = os.path.abspath(args.work)
    if os.path.exists(work):
        raise SystemExit("The folder %s already exists; choose a new one." % work)
    os.makedirs(work)
    repo = os.path.join(work, "repo")
    fixture = build(eco_dir, repo, args.prepare)
    with open(os.path.join(repo, "change-guard.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    cfg = cg.validate_config(raw)

    rows, failed = [], 0
    runs = [(c, c["branch"], c["branch"], None) for c in CASES]
    for v in VARIANTS + [dict(v, expect=tuple(v["expect"])) for v in fixture.get("variants", [])]:
        path = os.path.join(work, "config-%s.json" % re.sub(r"\W+", "-", v["name"]))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(raw, **v["config"]), fh, indent=2)
        runs.append((v, v["branch"], v["name"], path))
    for case, branch, label, config in runs:
        rc, out, data, secs = run_guard(repo, branch, work, label, config)
        files = new_test_files(eco_dir, branch, cfg)
        problems = check(case, data, files, rc)
        print("----- %s: %s -----" % (args.ecosystem, label))
        print(out.rstrip())
        status = "ok" if not problems else "FAILED"
        failed += bool(problems)
        print("%-6s %s: %s (%s) in %.1f s%s" % (status, label, data.get("result"), data.get("cause"), secs,
                                                 "" if not problems else " | " + "; ".join(problems)), flush=True)
        if problems and os.environ.get("GITHUB_ACTIONS") == "true":
            print("::error title=polyglot %s::%s: %s" % (args.ecosystem, label, "; ".join(problems)))
        classes = ", ".join(sorted(set(new_tests(case, data.get("classes")).values())))
        rows.append((label, "%s (%s)" % case["expect"], "%s (`%s`)" % (data.get("result"), data.get("cause")),
                     classes or "-", ", ".join(data.get("notes") or []) or "-", "%.1f s" % secs, status))

    if args.capture:
        capture(args.ecosystem, eco_dir, repo, work, cfg)

    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write("### change-guard %s on the %s fixture\n\n" % (cg.VERSION, args.ecosystem))
            if fixture.get("runner"):
                fh.write("Runner: %s. Report format: `%s`.\n\n" % (fixture["runner"], cfg["report_format"]))
            fh.write("| Case | Expected | Got | New tests on the base | Notes | Time | Check |\n|---|---|---|---|---|---|---|\n")
            for row in rows:
                fh.write("| %s |\n" % " | ".join(x.replace("|", "/") for x in row))
            fh.write("\n%d of %d cases as expected.\n\n" % (len(rows) - failed, len(rows)))
    print("%s: %d of %d cases as expected" % (args.ecosystem, len(rows) - failed, len(rows)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
