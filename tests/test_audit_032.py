# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Tests for version 0.3.2: the findings of the two re-audits of version 0.3.1.

Demo project, no real data. Run from the repository root:
    python3 -m unittest discover -s tests -v

Standard library only; the tests that need pytest skip without it. Each test
is named after its finding: RC-N1 to RC-N9 come from the code re-audit, RT-N1
to RT-N8 from the test re-audit, the other ids from the 0.3.0 audits (the list
at the end of CHANGELOG.md explains every id). The tests marked as controls
hold on 0.3.1 too: they show that the fix did not break the honest case.
"""

import errno
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_v21_fixes import BASE_CFG, ENV, GUARD, PRICING, Repo, cg, test_module  # noqa: E402

DISCOUNT = ("def line_total(price, qty):\n    total = price * qty\n    if qty >= 10:\n"
            "        total = total * 90 // 100\n    return total\n")
TEST_DISCOUNT = test_module("from src.pricing import line_total", "self.assertEqual(line_total(1000, 10), 9000)")
FORMAT = '\n\ndef format_price(cents):\n    return "EUR %d.%02d" % (cents // 100, cents % 100)\n'
TEST_FORMAT = test_module("from src.pricing import format_price", 'self.assertEqual(format_price(1234), "EUR 12.34")')
UNTESTED = "def line_total(price, qty):\n    return price * qty + 1\n"

try:
    import pytest  # noqa: F401
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

PYTEST_CFG = {"test_command": "{python} -m pytest -q -p no:cacheprovider --continue-on-collection-errors --junit-xml={report} {files}",
              "report_format": "junit-xml", "inconclusive_exit_codes": [3, 4]}


def guard(args, cwd=None, env=None):
    """The guard as a process; returns (exit code, output)."""
    e = dict(ENV)
    e.update(env or {})
    proc = subprocess.run([sys.executable, GUARD] + list(args), cwd=cwd, env=e,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def result_line(out):
    return next((l for l in out.splitlines() if l.startswith("result: ")), "")


# --------------------------------------------------------------------------
# Step 1: one-line and small fixes
# --------------------------------------------------------------------------

class RCN3Subfolder(unittest.TestCase):
    def test_rc_n3_a_run_in_a_subfolder_judges_the_whole_checkout(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        sub = os.path.join(r.repo, "src")
        code, res, out = r.run(repo=sub)
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)
        code, out = guard(["--base", "main", "--head", "change", "--mode", "block", "--log", os.path.join(r.root, "sub.log")], cwd=sub)
        self.assertEqual((result_line(out), code), ("result: PASSED (ok)", 0), out)

    def test_rc_n3_control_an_untested_change_is_still_stopped_from_a_subfolder(self):
        r = Repo(self)
        r.change({"src/pricing.py": UNTESTED})
        code, res, out = r.run(repo=os.path.join(r.repo, "tests"))
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "no-test", 1), out)


class RCN5LineFeedNames(unittest.TestCase):
    def test_rc_n5_patterns_match_names_with_a_line_feed(self):
        for pattern, path in (("src/**", "src/de\n.py"), ("src/**", "src/a\nb/c.py"), ("*.py", "src/x\n.py"),
                              ("src/*.py", "src/a\rb.py")):
            with self.subTest(path=path):
                self.assertTrue(cg.glob_to_regex(pattern).match(path))
        self.assertFalse(cg.glob_to_regex("src/*.py").match("src/a/b.py"))
        self.assertFalse(cg.glob_to_regex("src/**").match("lib/src/x.py"))

    def test_rc_n5_a_new_file_with_a_line_feed_in_its_name_is_in_scope(self):
        r = Repo(self)
        code, res, out = r.change({"src/de\n.py": 'RATES = {"de": 190}\n'})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "no-test", 1), out)


class RCN6Annotations(unittest.TestCase):
    def test_rc_n6_a_carriage_return_in_a_file_name_cannot_start_an_annotation(self):
        r = Repo(self)
        name = "src/a\r::notice title=change-guard PASSED::made up by the pull request\rz.py"
        summary = os.path.join(r.root, "summary.md")
        code, res, out = r.change({name: "X = 1\n"}, env={"GITHUB_ACTIONS": "true"}, args=("--summary", summary))
        self.assertEqual((res["result"], code), ("STOPPED", 1), out)
        # Read the output the way a reader that also ends a line at a lone carriage return does.
        commands = [l for l in out.replace("\r", "\n").splitlines() if l.startswith("::")]
        self.assertEqual(len(commands), 1, commands)
        self.assertTrue(commands[0].startswith("::error title=change-guard STOPPED::"), commands)
        self.assertIn("\\x0d", commands[0])
        with open(summary, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("\r", text)
        self.assertEqual([l for l in text.splitlines() if l.startswith("#")], ["### change-guard: STOPPED (no-test), mode block"])

    def test_rc_n6_html_and_markdown_from_the_change_are_shown_as_text(self):
        r = Repo(self)
        summary = os.path.join(r.root, "summary.md")
        code, res, out = r.change({"src/<h3>change-guard PASSED</h3>[x](https:__e.invalid).py": "X = 1\n"},
                                  args=("--summary", summary))
        self.assertEqual(res["result"], "STOPPED", out)
        with open(summary, encoding="utf-8") as fh:
            text = fh.read()
        # The log line at the end sits in a fenced code block, where nothing is read as Markdown or HTML.
        prose, fence, rest = text.partition("```\n")
        self.assertTrue(fence and rest.rstrip().endswith("```") and rest.count("\n") == 2, text)
        self.assertNotIn("<h3>", prose)
        self.assertIn("&lt;h3&gt;change\\-guard PASSED&lt;/h3&gt;\\[x\\]\\(https\\:\\_\\_e\\.invalid\\)", text)

    def test_rc_n6_the_helpers(self):
        self.assertEqual(cg.one_line("a\rb\nc d\x85e\x1bf"), "a\\x0db\\x0ac\\u2028d\\x85e\\x1bf")
        self.assertEqual(cg.markdown_text("| `x` <b> & *y*"), "\\| \\`x\\` &lt;b&gt; &amp; \\*y\\*")

    def test_rc_n6_a_percent_sign_is_escaped_in_the_annotation(self):
        r = Repo(self)
        code, res, out = r.change({"src/a%0A::notice::x.py": "X = 1\n"}, env={"GITHUB_ACTIONS": "true"})
        line = next(l for l in out.splitlines() if l.startswith("::error"))
        self.assertIn("a%250A::notice::x.py", line)


class RTN4LinkedPythonPath(unittest.TestCase):
    def test_rt_n4_pythonpath_through_a_link_is_moved(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "real")
            os.makedirs(os.path.join(real, "src"))
            link = os.path.join(d, "link")
            os.symlink(real, link)
            work = os.path.join(d, "wt")
            for repo in (real, link):
                with self.subTest(repo=repo):
                    for entry in (os.path.join(link, "src"), os.path.join(real, "src")):
                        self.assertEqual(cg.worktree_pythonpath(entry, repo, work), os.path.join(work, "src"))
            # Control: a folder outside the checkout stays as it is.
            self.assertEqual(cg.worktree_pythonpath(d, real, work), d)


class RTN5ModeOption(unittest.TestCase):
    def test_rt_n5_the_mode_option_ignores_case_and_spaces(self):
        r = Repo(self)
        r.change({"src/pricing.py": UNTESTED})
        for mode in ("Block", " BLOCK ", "block\t"):
            with self.subTest(mode=mode):
                code, res, out = r.run(mode=mode)
                self.assertEqual((res["result"], res["cause"], res["mode"], code), ("STOPPED", "no-test", "block", 1), out)
        code, res, out = r.run(mode="Report")
        self.assertEqual((res["result"], res["mode"], code), ("STOPPED", "report", 0), out)

    def test_rt_n5_an_unknown_mode_option_fails_closed_with_a_log_line(self):
        r = Repo(self)
        r.change({"src/pricing.py": UNTESTED})
        log = os.path.join(r.root, "mode.log")
        for mode in ("blocking", "on", "   "):
            with self.subTest(mode=mode):
                code, res, out = r.run(mode=mode, log=log)
                self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
                self.assertIn("--mode must be report or block", res["message"])
        with open(log, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 3)


class D11Values(unittest.TestCase):
    def test_d11_strings_booleans_and_negative_counts_are_refused(self):
        for key, value in (("time_budget_seconds", "300"), ("time_budget_seconds", True), ("time_budget_seconds", float("nan")),
                           ("time_budget_seconds", float("inf")), ("probe_time_budget_seconds", "60"),
                           ("output_tail_lines", -3), ("skip_reason_min_length", -1), ("output_tail_lines", "12"),
                           ("skip_reason_min_length", 2.5), ("base_repeats", True)):
            with self.subTest(key=key, value=value):
                with self.assertRaises(cg.GuardStop) as ctx_:
                    cg.validate_config(dict(BASE_CFG, **{key: value}))
                self.assertEqual(ctx_.exception.cause, "config")
                self.assertIn(key, ctx_.exception.message)

    def test_d11_control_numbers_still_load(self):
        c = cg.validate_config(dict(BASE_CFG, time_budget_seconds=30, output_tail_lines=0, skip_reason_min_length=0,
                                    probe_time_budget_seconds=1.5))
        self.assertEqual((c["time_budget_seconds"], c["output_tail_lines"], c["skip_reason_min_length"]), (30.0, 0, 0))

    def test_d11_a_time_budget_option_that_is_not_above_zero_is_refused(self):
        r = Repo(self)
        r.change({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        for value in ("0", "-5", "nan"):
            with self.subTest(value=value):
                code, res, out = r.run(args=("--time-budget", value))
                self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
                self.assertIn("--time-budget must be a number of seconds above zero", res["message"])
        code, res, out = r.run(args=("--time-budget", "60"))
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)

    def test_d11_tests_patterns_that_cover_every_protected_file_are_refused(self):
        r = Repo(self, config={"tests": ["src/**"]})
        code, res, out = r.change({"src/pricing.py": UNTESTED})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
        self.assertIn("protects nothing", res["message"])
        self.assertIn("'src/**'", res["message"])

    def test_d11_one_covered_pattern_of_several_gets_a_note(self):
        r = Repo(self, config={"protected": ["src/**", "lib/**"], "tests": ["tests/**/test_*.py", "lib/**"]},
                 base_files={"lib/helper.py": "X = 1\n"})
        code, res, out = r.change({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertIn("tests-cover-protected", res["notes"])
        self.assertIn("'lib/**'", res["note"])

    def test_d11_control_overlap_is_normal(self):
        r = Repo(self, config={"tests": ["src/**/test_*.py"]})
        test = test_module("from src.pricing import line_total", "self.assertEqual(line_total(1000, 10), 9000)")
        code, res, out = r.change({"src/pricing.py": DISCOUNT, "src/test_bulk.py": test})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertNotIn("tests-cover-protected", res["notes"])
        code, res, out = r.change({"src/pricing.py": UNTESTED})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "no-test"), out)


class Wording032(unittest.TestCase):
    def test_the_verdict_names_a_missing_file_not_a_class_of_the_guard(self):
        r = Repo(self)
        rate = "\n\ndef rate(code):\n    return {'nl': 210}[code]\n"
        data_test = test_module("import json", "with open('src/rates.json') as fh:\n    self.assertEqual(json.load(fh)['nl'], 210)")
        code, res, out = r.change({"src/pricing.py": PRICING + rate, "src/rates.json": '{"nl": 210}\n',
                                   "tests/test_rate.py": test_module("from src.pricing import rate", "self.assertEqual(rate('nl'), 210)"),
                                   "tests/test_data.py": data_test})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)
        self.assertIn("the files src/rates.json, which no probe covered", res["message"])
        self.assertNotIn("errored-missing-file", res["message"])

    def test_the_note_on_edited_code_reads_plainly(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": DISCOUNT + FORMAT, "tests/test_format.py": TEST_FORMAT})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)
        self.assertIn("this change also edits existing code (line_total), and no test showed failing", res["note"])
        self.assertIn("but not the edits to existing code (line_total)", res["message"])


# --------------------------------------------------------------------------
# Step 2: which edited files are laid over the base (RC-N1, RC-N8)
# --------------------------------------------------------------------------

UTIL_BASE = {"tests/util.py": "def make_cart():\n    return []\n"}
UTIL_HEAD = "def make_cart():\n    return []\n\n\ndef make_order():\n    return (1000, 10)\n"
IMPORT_STYLES = (("from tests import util\nfrom src.pricing import line_total", "util.make_order()"),
                 ("from tests.util import make_order\nfrom src.pricing import line_total", "make_order()"))


def rcn8_gitlink(r, path, sha):
    r.git("update-index", "--add", "--cacheinfo", "160000,%s,%s" % (sha, path))


class RCN1Overlay(unittest.TestCase):
    def test_i3_stays_stopped_in_both_import_styles(self):
        for imports, call in IMPORT_STYLES:
            with self.subTest(call=call):
                r = Repo(self, base_files=UTIL_BASE)
                test = test_module(imports, "self.assertTrue(line_total(*%s) > 0)" % call)
                code, res, out = r.change({"src/pricing.py": UNTESTED, "tests/util.py": UTIL_HEAD, "tests/test_o.py": test})
                self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "test-passes-on-base", 1), out)

    def test_i3_control_the_honest_version_passes(self):
        for imports, call in IMPORT_STYLES:
            with self.subTest(call=call):
                r = Repo(self, base_files=UTIL_BASE)
                test = test_module(imports, "self.assertEqual(line_total(*%s), 9000)" % call)
                code, res, out = r.change({"src/pricing.py": DISCOUNT, "tests/util.py": UTIL_HEAD, "tests/test_o.py": test})
                self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)

    def test_rc_n1a_an_edited_data_file_stays_as_it_is_on_the_base(self):
        reader = ('import json, os\n\n\ndef rate(country):\n    with open(os.path.join(os.path.dirname(__file__), "..", "data", "rates.json")) as fh:\n'
                  '        return %s[country]\n')
        r = Repo(self, base_files={"data/rates.json": '{"nl": 210, "be": 210}\n', "src/rates.py": reader % "json.load(fh)"})
        code, res, out = r.change({"data/rates.json": '[["nl", 210], ["be", 2100]]\n', "src/rates.py": reader % "dict(json.load(fh))",
                                   "tests/test_rates.py": test_module("from src.rates import rate", 'rate("be")')})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "test-passes-on-base", 1), out)

    def test_rc_n1b_an_edited_helper_outside_the_tests_stays_as_it_is_on_the_base(self):
        r = Repo(self, base_files={"lib/__init__.py": "", "lib/money.py": "def round_cents(value):\n    return int(round(value))\n",
                                   "src/pricing.py": "from lib.money import round_cents\n\n\ndef line_total(price, qty):\n"
                                                     "    return round_cents(price * qty)\n"})
        head = ("from lib.money import round_money\n\n\ndef line_total(price, qty):\n    t = price * qty\n"
                "    if qty >= 10:\n        t = t * 0.9\n    return round_money(t)\n")
        code, res, out = r.change({"lib/money.py": "def round_money(value):\n    return int(round(value))\n", "src/pricing.py": head,
                                   "tests/test_bulk.py": TEST_DISCOUNT})
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)

    def test_rc_n1_a_helper_next_to_a_changed_test_is_test_material(self):
        # The folder of a changed test file counts, also outside the literal folder of the tests pattern.
        r = Repo(self, config={"tests": ["**/test_*.py"]}, base_files={"checks/__init__.py": "", "checks/util.py": "def make_cart():\n    return []\n"})
        test = test_module("from checks.util import make_order\nfrom src.pricing import line_total", "self.assertTrue(line_total(*make_order()) > 0)")
        code, res, out = r.change({"src/pricing.py": UNTESTED, "checks/util.py": UTIL_HEAD, "checks/test_o.py": test})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "test-passes-on-base"), out)

    def test_rc_n1_the_rule(self):
        material = cg.test_material_rule(["tests/**/test_*.py", "./spec/", "*_test.go", "**/test_*.py"], ["pkg/a/test_x.py", "test_top.py"])
        for path, want in (("tests/util.py", True), ("tests/deep/data.json", True), ("spec/helper.rb", True),
                           ("pkg/a/conftest.py", True), ("pkg/a/b/data.json", True), ("pkg/other.py", False),
                           ("lib/money.py", False), ("data/rates.json", False), ("pom.xml", False), ("testsx/a.py", False)):
            with self.subTest(path=path):
                self.assertEqual(material(path), want)


class RCN8LinksAndSubmodules(unittest.TestCase):
    def test_rc_n8_the_report_case_an_edited_link_outside_the_tests(self):
        r = Repo(self, base_files={"conf/real.ini": "limit = 10\n"})
        os.symlink("real.ini", os.path.join(r.repo, "conf", "current.ini"))
        r.git("add", "-A")
        r.git("commit", "--quiet", "-m", "base with a link")
        r.git("checkout", "--quiet", "-B", "change", "main")
        os.remove(os.path.join(r.repo, "conf", "current.ini"))
        os.symlink("other.ini", os.path.join(r.repo, "conf", "current.ini"))
        r.commit({"conf/other.ini": "limit = 20\n", "src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        code, res, out = r.run()
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)

    def test_rc_n8_a_link_among_the_laid_over_files_is_replaced_not_written_through(self):
        r = Repo(self, base_files={"tests/data/real.ini": "limit = 10\n"})
        os.symlink("real.ini", os.path.join(r.repo, "tests", "data", "current.ini"))
        r.git("add", "-A")
        r.git("commit", "--quiet", "-m", "base with a link in the tests")
        r.git("checkout", "--quiet", "-B", "change", "main")
        os.remove(os.path.join(r.repo, "tests", "data", "current.ini"))
        os.symlink("other.ini", os.path.join(r.repo, "tests", "data", "current.ini"))
        test = test_module("from src.pricing import line_total",
                           "with open('tests/data/current.ini') as fh:\n    self.assertEqual(fh.read(), 'limit = 20\\n')\n"
                           "self.assertEqual(line_total(1000, 10), 9000)")
        r.commit({"tests/data/other.ini": "limit = 20\n", "src/pricing.py": DISCOUNT, "tests/test_bulk.py": test})
        code, res, out = r.run()
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)

    def test_rc_n8_submodule_pointers_are_left_alone(self):
        r = Repo(self)
        rcn8_gitlink(r, "tests/vendor", "1" * 40)
        r.git("commit", "--quiet", "-m", "base with a submodule pointer")
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        rcn8_gitlink(r, "tests/vendor", "2" * 40)
        rcn8_gitlink(r, "vendor/added", "3" * 40)
        r.git("commit", "--quiet", "-m", "move the pointer and add one")
        code, res, out = r.run()
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)


# --------------------------------------------------------------------------
# Step 3: the repair of a pattern that protects nothing (RC-N2, RT-N3)
# --------------------------------------------------------------------------

class RCN2ConfigRepair(unittest.TestCase):
    def setUp(self):
        # Two protected folders; the clean-up that removes the last file of legacy/ is merged.
        self.r = Repo(self, config={"protected": ["src/**", "legacy/**"]}, base_files={"legacy/old.py": "X = 1\n"})
        self.r.git("rm", "--quiet", "legacy/old.py")
        self.r.git("commit", "--quiet", "-m", "remove the legacy folder")
        self.fixed = json.dumps(dict(BASE_CFG, protected=["src/**"]))

    def test_rc_n2_the_whole_story(self):
        r = self.r
        code, res, out = r.change({"docs/notes.md": "Notes.\n"})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
        self.assertIn("'legacy/**'", res["message"])
        self.assertIn("config-repair", out.split("what to do:")[1])
        self.assertIn("skip step", out.split("what to do:")[1])
        code, res, out = r.change({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
        code, res, out = r.change({"change-guard.json": self.fixed})
        self.assertEqual((res["result"], res["cause"], code), ("EXEMPT", "config-repair", 0), out)
        self.assertIn("config-repair", res["notes"])
        self.assertIn("guard-changed", res["notes"])
        # The repair is merged; the next honest change passes.
        r.git("checkout", "--quiet", "main")
        r.git("merge", "--quiet", "--ff-only", "change")
        code, res, out = r.change({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)

    def test_rc_n2_a_repair_must_leave_no_pattern_that_protects_nothing(self):
        for cfg in (dict(BASE_CFG, protected=["src/**", "gone/**"]), dict(BASE_CFG, protected=["src/**"], tests=["src/**"])):
            with self.subTest(cfg=cfg):
                code, res, out = self.r.change({"change-guard.json": json.dumps(cfg)})
                self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)

    def test_rc_n2_a_repair_must_touch_nothing_else(self):
        code, res, out = self.r.change({"change-guard.json": self.fixed, "src/pricing.py": UNTESTED})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
        code, res, out = self.r.change({"change-guard.json": "{not json"})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)

    def test_rc_n2_control_the_skip_step_still_works(self):
        code, res, out = self.r.change({"docs/notes.md": "Notes.\n"},
                                       args=("--skip-by", "anna", "--skip-reason", "Repairs the guard configuration"))
        self.assertEqual((res["result"], res["cause"], code), ("SKIPPED", "skip", 0), out)

    def test_i7_control_an_unmatched_pattern_stays_an_error_for_other_changes(self):
        r = Repo(self, config={"protected": ["src/**", "lib/**"]})
        code, res, out = r.change({"src/pricing.py": UNTESTED})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)


# --------------------------------------------------------------------------
# Step 4: pytest assertion failures keep their class (RC-N4)
# --------------------------------------------------------------------------

# What pytest 9.0.3 wrote with --junit-xml for three failing tests (a plain
# numeric assertion, an assertion with a message, an assertion in a helper the
# test calls) and one exception; the text is cut to its first and last lines.
PYTEST_XML = """<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest" errors="0" failures="4" skipped="0" tests="4">
<testcase classname="tests.test_bulk" name="test_a" time="0.001"><failure message="assert 10000 == 9000&#10; +  where 10000 = total(1000, 10)">def test_a():
        # the old code raised KeyError: 'bulk' for large orders; discount is not defined
&gt;       assert total(1000, 10) == 9000
E       assert 10000 == 9000
E        +  where 10000 = total(1000, 10)

tests/test_bulk.py:4: AssertionError</failure></testcase>
<testcase classname="tests.test_bulk" name="test_b" time="0.001"><failure message="AssertionError: wrong&#10;assert 2 == 3">E       AssertionError: wrong

tests/test_bulk.py:9: AssertionError</failure></testcase>
<testcase classname="tests.test_bulk" name="test_c" time="0.001"><failure message="assert 0">    def helper(v):
&gt;       assert v
E       assert 0

tests/test_bulk.py:12: AssertionError</failure></testcase>
<testcase classname="tests.test_bulk" name="test_d" time="0.001"><failure message="KeyError: 'bulk'">E       KeyError: 'bulk'

tests/test_bulk.py:15: KeyError</failure></testcase>
</testsuite></testsuites>"""


class RCN4PytestAssertions(unittest.TestCase):
    def ctx(self, added=()):
        c = cg.validate_config(dict(BASE_CFG))
        return {"added": set(added), "added_paths": [], "missing_rx": c["_missing_rx"], "env_patterns": c["_env_patterns"]}

    def test_rc_n4_every_pytest_assertion_keeps_its_class(self):
        recs = {r["id"].split(".")[-1]: r for r in cg.parse_junit_xml([PYTEST_XML])}
        for name in ("test_a", "test_b", "test_c"):
            with self.subTest(name=name):
                self.assertEqual((recs[name]["outcome"], recs[name]["type"]), ("failed", "AssertionError"))
        self.assertEqual((recs["test_d"]["outcome"], recs["test_d"]["type"]), ("error", "KeyError"))
        head = [cg._rec(r["id"], r["group"], "passed") for r in recs.values()]
        classes = cg.classify_base(head, list(recs.values()), self.ctx(added={"discount"}))
        self.assertEqual([classes["tests.test_bulk." + n][0] for n in ("test_a", "test_b", "test_c")], ["failed-assertion"] * 3)

    def test_rc_n4_control_a_failure_with_a_type_or_without_assert_is_read_as_before(self):
        xml = ('<testsuite><testcase classname="t" name="a"><failure type="org.opentest4j.AssertionFailedError" message="expected: 9000">x</failure></testcase>'
               '<testcase classname="t" name="b"><failure message="Failed: DID NOT RAISE">x</failure></testcase></testsuite>')
        recs = cg.parse_junit_xml([xml])
        self.assertEqual([(r["outcome"], r["type"]) for r in recs], [("failed", "org.opentest4j.AssertionFailedError"), ("failed", "")])

    @unittest.skipUnless(HAS_PYTEST, "pytest is not installed")
    def test_rc_n4_words_in_the_test_source_do_not_change_the_verdict(self):
        comments = ("", "# the old code raised KeyError: 'bulk' for large orders\n    ", "# discount is not defined\n    ",
                    "# has no attribute 'discount'\n    ", "# applyDiscount is not a function\n    ",
                    "note = \"cannot import name 'discount'\"\n    ")
        for comment in comments:
            with self.subTest(comment=comment):
                r = Repo(self, config=PYTEST_CFG)
                test = "from src.pricing import line_total\n\n\ndef test_bulk():\n    %sassert line_total(1000, 10) == 9000\n" % comment
                code, res, out = r.change({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": test})
                self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)
                self.assertEqual(res["classes"], {"tests.test_bulk.test_bulk": "failed-assertion"}, out)
                self.assertNotIn("changed-code-unproven", res["notes"])
                code, res, out = r.run(args=("--config", self.stop_config(r)))
                self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)

    def stop_config(self, r):
        path = os.path.join(r.root, "stop.json")
        with open(path, "w") as fh:
            json.dump(dict(BASE_CFG, base_error_policy="stop", **PYTEST_CFG), fh)
        return path


# --------------------------------------------------------------------------
# Step 5: the log lock (RC-N7, RT-N1, RT-N7)
# --------------------------------------------------------------------------

class HeldLock:
    """The lock next to a log, held by this test process like another guard run would hold it."""

    def __init__(self, log, seconds=None):
        import fcntl
        self.fh = open(log + ".lock", "a+")
        fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.timer = threading.Timer(seconds, self.release) if seconds else None
        if self.timer:
            self.timer.start()

    def release(self):
        if not self.fh.closed:
            self.fh.close()


SLOW_HONEST = test_module("import time\nfrom src.pricing import line_total", "time.sleep(0.5)\nself.assertEqual(line_total(1000, 10), 9000)")


@unittest.skipIf(os.name == "nt", "the log lock uses fcntl")
class LogLock032(unittest.TestCase):
    def test_rc_n7_the_wait_for_the_lock_does_not_count_against_the_budget(self):
        r = Repo(self)
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": SLOW_HONEST})
        log = os.path.join(r.root, "runs.log")
        held = HeldLock(log, 4)
        self.addCleanup(held.release)
        started = time.monotonic()
        code, res, out = r.run(args=("--time-budget", "5"))
        self.assertGreater(time.monotonic() - started, 4)
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)
        self.assertIn("waiting for another change guard run", out)
        with open(log, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 1)

    def test_rt_n1_a_lock_busy_for_longer_than_the_budget_ends_as_error_log_busy(self):
        r = Repo(self)
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        log = os.path.join(r.root, "runs.log")
        held = HeldLock(log)
        self.addCleanup(held.release)
        for mode, want_code in (("block", 2), ("report", 0)):
            with self.subTest(mode=mode):
                code, res, out = r.run(mode=mode, args=("--time-budget", "1"))
                self.assertEqual((res["result"], res["cause"], code), ("ERROR", "log-busy", want_code), out)
                self.assertIn("Run the job again", out)
                self.assertNotIn("head:", out)
        # The run did not write into the log the other run holds, and did not run unlocked.
        self.assertFalse(os.path.exists(log))

    def test_rt_n7_a_lock_file_that_cannot_be_created_names_the_cause_and_does_not_wait(self):
        r = Repo(self)
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        blocker = os.path.join(r.root, "a-file")
        with open(blocker, "w") as fh:
            fh.write("x")
        started = time.monotonic()
        code, res, out = r.run(log=os.path.join(blocker, "x", "runs.log"))
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertIn("log-unlocked", res["notes"])
        self.assertIn("could not create the lock file", res["note"])
        self.assertNotIn("longer than the time budget", out)
        self.assertNotIn("waiting for another", out)

    def test_rt_n7_a_file_system_that_refuses_locks_does_not_wait(self):
        import fcntl
        with tempfile.TemporaryDirectory() as d:
            lock = cg.LogLock(os.path.join(d, "runs.log"))
            with unittest.mock.patch.object(fcntl, "flock", side_effect=OSError(errno.ENOLCK, "No locks available")):
                started = time.monotonic()
                status, detail = lock.acquire(30)
            lock.release()
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(status, "unlocked")
        self.assertIn("No locks available", detail)

    def test_rt_n7_only_a_busy_lock_is_waited_for(self):
        import fcntl
        with tempfile.TemporaryDirectory() as d:
            lock = cg.LogLock(os.path.join(d, "runs.log"))
            with unittest.mock.patch.object(fcntl, "flock", side_effect=BlockingIOError(errno.EWOULDBLOCK, "busy")):
                started = time.monotonic()
                status, _ = lock.acquire(1)
            lock.release()
        self.assertGreaterEqual(time.monotonic() - started, 1)
        self.assertEqual(status, "busy")


# --------------------------------------------------------------------------
# Step 6: the smaller code points
# --------------------------------------------------------------------------

class M4ReportFolder(unittest.TestCase):
    def test_m4_a_test_cannot_count_earlier_reports(self):
        wrong = "def line_total(price, qty):\n    return price * qty + 999\n"
        for name, body in (
                ("code re-audit", 'folder = os.path.dirname(os.environ["CHANGE_GUARD_REPORT"])\n'
                                  'self.assertEqual(len([n for n in os.listdir(folder) if not n.endswith(".tmp")]), 0)'),
                ("test re-audit", 'd = os.path.dirname(os.environ["CHANGE_GUARD_REPORT"])\n'
                                  'self.assertEqual([f for f in os.listdir(d) if f.endswith(".jsonl")], [])'),
                ("one folder up", 'up = os.path.dirname(os.path.dirname(os.environ["CHANGE_GUARD_REPORT"]))\n'
                                  'self.assertEqual(len(os.listdir(up)), 1)')):
            with self.subTest(name=name):
                r = Repo(self)
                code, res, out = r.change({"src/pricing.py": wrong, "tests/test_bulk.py": test_module("import os", body)})
                self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "test-passes-on-base", 1), out)


CART = "class Cart:\n    TAX = 21\n\n    def total(self, cents):\n        return cents * (100 + self.TAX) // 100\n"
D1_CASES = (
    ("a class attribute", CART, CART.replace("TAX = 21", "TAX = 12"), "Cart.TAX"),
    ("a replaced decorator",
     "import functools\n\n\n@functools.lru_cache(maxsize=None)\ndef rate(code):\n    return {'nl': 21}.get(code, 0)\n",
     "import functools\n\n\n@functools.lru_cache(maxsize=1)\ndef rate(code):\n    return {'nl': 21}.get(code, 0)\n",
     "the decorators of rate"),
    ("a module-level statement", "RATES = {}\nRATES.update(nl=21)\n", "RATES = {}\nRATES.update(nl=12)\n", "module-level code"),
    ("a deleted function", "def legacy_rate():\n    return 21\n\n\ndef rate():\n    return 21\n", "def rate():\n    return 21\n",
     "legacy_rate (deleted)"),
)


class D1Rest(unittest.TestCase):
    def stop_config(self, r):
        path = os.path.join(r.root, "stop.json")
        with open(path, "w") as fh:
            json.dump(dict(BASE_CFG, base_error_policy="stop"), fh)
        return path

    def test_d1_edits_that_are_not_function_bodies_get_the_note(self):
        for name, base, head, label in D1_CASES:
            with self.subTest(name=name):
                r = Repo(self, base_files={"src/cart.py": base})
                code, res, out = r.change({"src/cart.py": head + FORMAT,
                                           "tests/test_format.py": TEST_FORMAT.replace("src.pricing", "src.cart")})
                self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok-unproven", 0), out)
                self.assertIn("changed-code-unproven", res["notes"])
                self.assertIn(label, res["note"])
                code, res, out = r.run(args=("--config", self.stop_config(r)))
                self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "base-error-only", 1), out)

    def test_d1_control_docstrings_comments_imports_and_exports_give_no_note(self):
        base = ('"""Prices."""\nfrom decimal import Decimal\n\n__all__ = ["Cart"]\n\n\nclass Cart:\n    """A cart."""\n    TAX = 21\n\n'
                '    def total(self, cents):\n        """Total in cents."""\n        return cents * (100 + self.TAX) // 100  # with tax\n')
        head = ('"""Prices, in cents."""\nfrom decimal import Decimal, ROUND_HALF_UP\n\n__all__ = ["Cart", "format_price"]\n\n\nclass Cart:\n'
                '    """A shopping cart."""\n    TAX = 21\n\n    def total(self, cents):\n        """The total in cents, tax included."""\n'
                '        return cents * (100 + self.TAX) // 100  # tax included\n')
        r = Repo(self, base_files={"src/cart.py": base})
        code, res, out = r.change({"src/cart.py": head + FORMAT, "tests/test_format.py": TEST_FORMAT.replace("src.pricing", "src.cart")})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-new-code"), out)
        self.assertNotIn("changed-code-unproven", res["notes"])

    def test_d1_the_labels(self):
        import ast
        base = ("import os\nfrom a import b\nX = 1\n\n\nclass C(object):\n    Y = 2\n\n    def m(self):\n        return 1\n\n\n"
                "@d\ndef f():\n    pass\n\n\ndef g():\n    pass\n\n\nprint(X)\n")
        head = ("import os, sys\nfrom c import b\nX = 1\n\n\nclass C(dict):\n    Y = 3\n\n    def m(self):\n        return 1\n\n\n"
                "def f():\n    pass\n\n\nprint(X + 1)\n")
        labels = cg.python_edits(ast.parse(base), ast.parse(head), cg.python_definitions(base)[0], cg.python_definitions(head)[0])
        self.assertEqual(labels, ["the decorators of f", "g (deleted)", "the header of class C", "an import in the module",
                                  "module-level code", "C.Y"])


class RTN6NoReport(unittest.TestCase):
    """report_format "none" with a runner outside Python: the exit code decides, and a missing name gets a note."""

    RUNNER = ("import sys\nsrc = open('src/Discount.java').read() if __import__('os').path.exists('src/Discount.java') else ''\n"
              "if 'class Discount' not in src:\n"
              "    print('src/test/DiscountTest.java:3: error: cannot find symbol')\n    print('  symbol:   class Discount')\n    sys.exit(1)\n")

    def test_rt_n6_a_call_only_test_of_a_new_name_gets_a_note(self):
        r = Repo(self, config={"report_format": "none", "test_command": "{python} {files}", "tests": ["checks/**/*_check.py"]})
        code, res, out = r.change({"src/Discount.java": "public final class Discount {\n  static long apply(long c) { return c; }\n}\n",
                                   "checks/discount_check.py": self.RUNNER})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertIn("suspect-base-output", res["notes"])
        self.assertIn("'cannot find symbol'", res["note"])

    def test_rt_n6_the_list(self):
        for text in ("cannot find symbol", "is not a function", "is not defined", "has no attribute", "cannot import name"):
            self.assertIn(text, cg.DEFAULTS["suspect_base_failure_patterns"])


class RCN9BareFolders(unittest.TestCase):
    def fake_bare(self, folder):
        os.makedirs(os.path.join(folder, "objects", "info"))
        os.makedirs(os.path.join(folder, "refs", "heads"))
        with open(os.path.join(folder, "HEAD"), "w") as fh:
            fh.write("ref: refs/heads/main\n")
        with open(os.path.join(folder, "config"), "w") as fh:
            fh.write("[core]\n\trepositoryformatversion = 0\n\tbare = true\n")

    def test_rc_n9_a_folder_that_looks_like_a_bare_repository_is_not_taken(self):
        r = Repo(self)
        svc = os.path.join(r.repo, "svc")
        self.fake_bare(svc)
        plain = subprocess.run(["git", "-C", svc, "rev-parse", "--git-dir"], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cg._git_setup()
        self.assertIn("safe.bareRepository=explicit", cg._GIT["args"])
        code, res, out = r.run(repo=svc)
        if plain.returncode == 0 and plain.stdout.strip() == b".":
            # This git reads the folder as a repository of its own; the guard must refuse it.
            self.assertEqual((res["result"], res["cause"], code), ("ERROR", "git", 2), out)
            # Since 0.3.3 (C-N4) the refusal names the bare repository it found.
            self.assertRegex(res["message"], "is not a git repository|is a bare repository")
        else:
            self.assertNotEqual(res["result"], "OUT_OF_SCOPE", out)

    def test_rc_n9_control_a_linked_worktree_still_works(self):
        r = Repo(self)
        r.change({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        r.git("checkout", "--quiet", "main")
        linked = os.path.join(r.root, "linked")
        r.git("worktree", "add", "--quiet", "--detach", linked, "change")
        code, res, out = r.run(repo=linked)
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)


if __name__ == "__main__":
    unittest.main()
