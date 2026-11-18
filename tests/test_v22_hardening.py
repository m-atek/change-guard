# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Tests for the version 0.2.2 hardening (V3a, V3b, V4, V5, V7). Demo project, no real data.

Run from the repository root:  python3 -m unittest discover -s tests -v
Standard library only. The ids are those of the separate verification round of
version 0.2.1, listed in CHANGELOG.md. Every test here fails on the 0.2.1 code as
delivered and passes on 0.2.2, except the one marked as a regression check,
which holds on both.
"""

import json
import os
import stat
import subprocess
import sys
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_v21_fixes import BASE_CFG, ENV, FIXED, NEW_FN, PRICING, Repo, cg, test_module  # noqa: E402

# A change that breaks line_total: line_total(2, 3) is now 5.
BROKEN = "def line_total(price, qty):\n    return price + qty\n"
POISON = "import unittest\\nunittest.TestCase.setUp = lambda self: self.fail()\\n"

# The hook poisons every checkout that does not hold the broken code, so the
# head passes and the base fails "by assertion".
HOOK = "#!/bin/sh\ngrep -q 'price + qty' src/pricing.py 2>/dev/null || printf '%s' >> src/__init__.py\n" % POISON

TEST_PLANTS_HOOK = textwrap.dedent('''\
    import os, stat, subprocess, unittest
    from src.pricing import line_total

    HOOK = {hook!r}


    class T(unittest.TestCase):
        def test_line_total(self):
            common = subprocess.run(["git", "rev-parse", "--git-common-dir"], stdout=subprocess.PIPE).stdout.decode().strip()
            hook = os.path.join(os.path.abspath(common), "hooks", "post-checkout")
            if not os.path.exists(hook):
                with open(hook, "w") as fh:
                    fh.write(HOOK)
                os.chmod(hook, 0o755)
            line_total(2, 3)
    ''').format(hook=HOOK)

TEST_CHANGES_GIT_CONFIG = textwrap.dedent('''\
    import os, subprocess, unittest
    from src.pricing import line_total


    class T(unittest.TestCase):
        def test_line_total(self):
            common = subprocess.run(["git", "rev-parse", "--git-common-dir"], stdout=subprocess.PIPE).stdout.decode().strip()
            with open(os.path.join(os.path.abspath(common), "config"), "a") as fh:
                fh.write("[core]\\n\\thooksPath = /tmp/elsewhere\\n")
            line_total(2, 3)
    ''')

TEST_CALLS_ONLY = test_module("from src.pricing import line_total", "line_total(2, 3)")

DAEMON = textwrap.dedent('''\
    import glob, os, sys, time
    mine, flag = sys.argv[1], sys.argv[2]
    parent = os.path.dirname(mine)
    end = time.time() + 15
    done = False
    while time.time() < end and not done:
        for d in glob.glob(os.path.join(parent, "wt-*")):
            init = os.path.join(d, "src", "__init__.py")
            if d != mine and os.path.exists(init):
                try:
                    with open(init, "a") as fh:
                        fh.write("import unittest\\nunittest.TestCase.setUp = lambda self: self.fail('planted')\\n")
                    open(flag, "a").close()
                    done = True
                except OSError:
                    pass
        time.sleep(0.005)
    ''')

TEST_STARTS_DAEMON = textwrap.dedent('''\
    import os, subprocess, sys, time, unittest
    from src.pricing import line_total


    class T(unittest.TestCase):
        def test_line_total(self):
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            parent = os.path.dirname(here)
            flag, started = os.path.join(parent, "patched"), os.path.join(parent, "daemon-started")
            if not os.path.exists(started):
                open(started, "w").close()
                subprocess.Popen([sys.executable, os.path.join(here, "tests", "daemon.txt"), here, flag],
                                 start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.time() + 3
                while time.time() < deadline and not os.path.exists(flag):
                    time.sleep(0.01)
            line_total(2, 3)
    ''')

TEST_GIT_STATUS_CLEAN = textwrap.dedent('''\
    import os, subprocess, unittest
    from src.pricing import line_total


    class T(unittest.TestCase):
        def test_line_total(self):
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            dirty = subprocess.run(["git", "status", "--porcelain"], cwd=here, stdout=subprocess.PIPE).stdout.strip()
            line_total(2, 3)
            self.assertEqual(dirty, b"")
    ''')


def test_records_worktree(seen):
    """A test that writes what git shows in its worktree to a file outside it, then tests honestly."""
    return textwrap.dedent('''\
        import os, subprocess, unittest

        # Recorded when the module loads, so the base run (where the import below fails) is seen too.
        HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        run = lambda *a: subprocess.run(["git"] + list(a), cwd=HERE, stdout=subprocess.PIPE).stdout.decode().strip()
        with open({seen!r}, "a") as fh:
            fh.write("status=%r log=%r\\n" % (run("status", "--porcelain"), run("log", "-1", "--format=%s|%an|%ae|%ad")))

        from src.pricing import bulk_total


        class T(unittest.TestCase):
            def test_bulk(self):
                self.assertEqual(bulk_total(10, 10), 90)
                self.assertEqual(bulk_total(10, 2), 20)
        ''').format(seen=seen)


def common_dir(r):
    return os.path.join(r.repo, ".git")


class V3aRepositoryHooksAndConfig(unittest.TestCase):
    def test_v3a_a_hook_planted_by_the_tests_is_removed_and_the_run_is_tampered(self):
        r = Repo(self)
        hook = os.path.join(common_dir(r), "hooks", "post-checkout")
        code, res, out = r.change({"src/pricing.py": BROKEN, "tests/test_line.py": TEST_PLANTS_HOOK})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "tampered", 2), out)
        self.assertIn(".git/hooks/post-checkout", res["message"], out)
        self.assertFalse(os.path.exists(hook), "the planted hook must be removed after the run")

    def test_v3a_git_configuration_changed_by_the_tests_is_restored(self):
        r = Repo(self)
        config = os.path.join(common_dir(r), "config")
        with open(config, "rb") as fh:
            before = fh.read()
        code, res, out = r.change({"src/pricing.py": BROKEN, "tests/test_line.py": TEST_CHANGES_GIT_CONFIG})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "tampered", 2), out)
        self.assertIn(".git/config", res["message"], out)
        with open(config, "rb") as fh:
            self.assertEqual(fh.read(), before)

    def test_v3a_a_hook_left_in_the_repository_does_not_run_for_the_guard(self):
        # A hook left by an earlier run on a reused workspace: 2.1 ran it for every
        # worktree it made, so the base failed "by assertion" and a test that
        # asserts nothing passed a broken change.
        r = Repo(self)
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": BROKEN, "tests/test_line.py": TEST_CALLS_ONLY})
        hook = os.path.join(common_dir(r), "hooks", "post-checkout")
        with open(hook, "w") as fh:
            fh.write(HOOK)
        os.chmod(hook, 0o755)
        code, res, out = r.run()
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "test-passes-on-base", 1), out)

    def test_v3a_the_users_git_configuration_is_not_read(self):
        # A hooks folder named in the user's global configuration, which the
        # tests of an earlier run could have written.
        r = Repo(self)
        hooks = os.path.join(r.root, "user-hooks")
        os.makedirs(hooks)
        with open(os.path.join(hooks, "post-checkout"), "w") as fh:
            fh.write(HOOK)
        os.chmod(os.path.join(hooks, "post-checkout"), 0o755)
        user_config = os.path.join(r.root, "user.gitconfig")
        with open(user_config, "w") as fh:
            fh.write("[core]\n\thooksPath = %s\n" % hooks)
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": BROKEN, "tests/test_line.py": TEST_CALLS_ONLY})
        code, res, out = r.run(env={"GIT_CONFIG_GLOBAL": user_config})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "test-passes-on-base", 1), out)


class V3bWorktreesAreChecked(unittest.TestCase):
    def test_v3b_a_daemon_that_patches_the_base_worktree_is_caught(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": BROKEN, "tests/test_line.py": TEST_STARTS_DAEMON,
                                   "tests/daemon.txt": DAEMON})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "tampered", 2), out)
        self.assertIn("prepared for the base run", res["message"], out)

    def test_v3b_the_seal_sees_tracked_untracked_and_written_files(self):
        r = Repo(self)
        wt = os.path.join(r.root, "wt-seal")
        cg.add_worktree(r.repo, "main", wt)
        self.addCleanup(cg.remove_worktree, r.repo, wt)
        with open(os.path.join(wt, "tests", "test_new.py"), "w") as fh:
            fh.write("# written by the guard\n")
        seal = cg.WorktreeSeal(wt, "base")
        seal.seal(cg.seal_commit(wt, ["tests/test_new.py"]), ["tests/test_new.py"])
        seal.verify()   # untouched: no error
        with open(os.path.join(wt, "left-by-the-run.txt"), "w") as fh:
            fh.write("a run may leave files\n")
        seal.after_run()
        seal.verify()   # what the run itself left is accepted
        for path, text in (("src/__init__.py", "X = 1\n"), ("tests/test_new.py", "# changed\n"), ("src/extra.py", "")):
            full = os.path.join(wt, *path.split("/"))
            with open(full, "a") as fh:
                fh.write(text)
            with self.assertRaises(cg.GuardStop) as ctx:
                seal.verify()
            self.assertEqual(ctx.exception.cause, "tampered")
            self.assertIn(path, ctx.exception.message)
            cg.git(wt, "checkout", "--quiet", "--", ".")
            if path == "src/extra.py":
                os.remove(full)
            seal.seal(seal.head, ["tests/test_new.py"])


class V4WorktreesLookAlike(unittest.TestCase):
    def test_v4_a_test_that_only_checks_git_status_no_longer_passes_a_broken_change(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": BROKEN, "tests/test_line.py": TEST_GIT_STATUS_CLEAN})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "test-passes-on-base", 1), out)

    def test_v4_head_base_and_probe_show_the_same_status_and_last_commit(self):
        r = Repo(self)
        seen = os.path.join(r.root, "seen.txt")
        code, res, out = r.change({"src/pricing.py": NEW_FN, "tests/test_bulk.py": test_records_worktree(seen)})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-new-code"), out)
        with open(seen) as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 4, lines)   # head, base twice, probe
        self.assertEqual(len(set(lines)), 1, lines)
        self.assertIn("status=''", lines[0])
        self.assertIn(cg.SEAL_MESSAGE, lines[0])


class V5WhitespaceOnlyInPython(unittest.TestCase):
    SCRIPT = "#!/bin/bash\nset -e\necho deploying\nexit 0\n"

    def test_v5_a_shell_script_converted_to_crlf_needs_a_test(self):
        r = Repo(self, base_files={"src/deploy.sh": self.SCRIPT})
        code, res, out = r.change({"src/deploy.sh": self.SCRIPT.replace("\n", "\r\n").encode()})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "no-test", 1), out)

    def test_v5_a_space_after_a_line_continuation_needs_a_test(self):
        r = Repo(self, base_files={"src/run.sh": "#!/bin/sh\necho start \\\n  --safe-mode\n"})
        code, res, out = r.change({"src/run.sh": "#!/bin/sh\necho start \\ \n  --safe-mode\n"})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "no-test", 1), out)

    def test_v5_trailing_whitespace_in_yaml_needs_a_test(self):
        r = Repo(self, base_files={"src/rules.yaml": "bulk: 10\n"})
        code, res, out = r.change({"src/rules.yaml": "bulk: 10   \r\n\n"})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "no-test", 1), out)

    def test_v5_regression_check_the_exempt_list_still_lets_such_files_through(self):
        # Holds on 0.2.1 as well: the project's exempt list decides, not the guard.
        r = Repo(self, config={"exempt": ["src/**/*.sh"]}, base_files={"src/deploy.sh": self.SCRIPT})
        code, res, out = r.change({"src/deploy.sh": self.SCRIPT.replace("\n", "\r\n").encode()})
        self.assertEqual((res["result"], res["cause"], code), ("EXEMPT", "exempt-only", 0), out)


class V7BrokenConfigurationOnTheBase(unittest.TestCase):
    TEST = test_module("from src.pricing import line_total", "self.assertEqual(line_total(-1, 2), 0)")

    def repo(self):
        return Repo(self, base_files={"change-guard.json": "{ not json"})

    def test_v7_the_skip_step_lets_the_repair_through_and_is_logged(self):
        r = self.repo()
        log = os.path.join(r.root, "runs.log")
        code, res, out = r.change({"change-guard.json": json.dumps(BASE_CFG), "src/pricing.py": FIXED,
                                   "tests/test_fixed.py": self.TEST},
                                  args=("--skip-by", "maintainer", "--skip-reason", "repairs the broken guard configuration"))
        self.assertEqual((res["result"], res["cause"], code), ("SKIPPED", "skip", 0), out)
        self.assertIn("config-broken", res["notes"], out)
        with open(log, encoding="utf-8") as fh:
            line = fh.read().splitlines()[-1].split("\t")
        self.assertEqual((line[2], line[3], line[11], line[12]),
                         ("SKIPPED", "skip", "maintainer", "repairs the broken guard configuration"))

    def test_v7_a_change_that_only_repairs_the_configuration_passes_with_a_note(self):
        r = self.repo()
        code, res, out = r.change({"change-guard.json": json.dumps(BASE_CFG)})
        self.assertEqual((res["result"], res["cause"], code), ("EXEMPT", "config-repair", 0), out)
        self.assertIn("config-repair", res["notes"], out)

    def test_v7_a_repair_that_also_changes_code_stays_an_error(self):
        r = self.repo()
        code, res, out = r.change({"change-guard.json": json.dumps(BASE_CFG), "src/pricing.py": "def line_total(price, qty):\n    return 0\n"})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
        self.assertIn("touches only change-guard.json", out)

    def test_v7_a_repair_that_does_not_load_either_stays_an_error(self):
        r = self.repo()
        code, res, out = r.change({"change-guard.json": "{ still not json"})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
        self.assertIn("touches only change-guard.json", out)

    def test_v7_a_skip_without_a_reason_is_refused(self):
        r = self.repo()
        code, res, out = r.change({"change-guard.json": json.dumps(BASE_CFG), "src/pricing.py": FIXED},
                                  args=("--skip-by", "maintainer", "--skip-reason", "fix"))
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "skip-no-reason", 1), out)


if __name__ == "__main__":
    unittest.main()
