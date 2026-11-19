# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Tests for version 0.3.3: the five points C-N1 to C-N5 of a check of version 0.3.2.

Demo project, no real data. Run from the repository root:
    python3 -m unittest discover -s tests -v

Standard library only; the tests that need pytest skip without it. C-N5 is a
text change and has no test here.
"""

import ast
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_v21_fixes import BASE_CFG, ENV, Repo, cg, test_module  # noqa: E402
from test_audit_032 import DISCOUNT, FORMAT, HAS_PYTEST, PYTEST_CFG, TEST_DISCOUNT, TEST_FORMAT  # noqa: E402

WRONG = "def line_total(price, qty):\n    return price * qty + 999\n"
CONFTEST = "import pytest\n\n\n@pytest.fixture\ndef small():\n    return (1000, 1)\n"
CONFTEST_HEAD = CONFTEST + "\n\n@pytest.fixture\ndef bulk():\n    return (1000, 10)\n"


def ctx(added=()):
    c = cg.validate_config(dict(BASE_CFG))
    return {"added": set(added), "added_paths": [], "missing_rx": c["_missing_rx"], "env_patterns": c["_env_patterns"]}


class CN1Conftest(unittest.TestCase):
    def test_c_n1_every_conftest_is_test_material(self):
        material = cg.test_material_rule(["tests/**/test_*.py"], ["tests/test_bulk.py"])
        for path in ("conftest.py", "src/conftest.py", "a/b/conftest.py"):
            self.assertTrue(material(path), path)
        self.assertFalse(material("src/conftest_helpers.py"))

    def test_c_n1_a_missing_fixture_is_a_missing_name(self):
        rec = cg._rec("tests.test_bulk.test_bulk", "tests.test_bulk", "error", "",
                      'failed on setup with "file tests/test_bulk.py, line 4\n  def test_bulk(bulk):\nE       fixture \'bulk\' not found')
        head = [cg._rec("tests.test_bulk.test_bulk", "tests.test_bulk", "passed")]
        self.assertEqual(cg.classify_base(head, [rec], ctx())["tests.test_bulk.test_bulk"][0], "errored-unknown-name")

    def test_c_n1_the_recommended_pattern_covers_a_root_conftest(self):
        rx = cg.glob_to_regex("**/conftest.py")
        self.assertTrue(rx.match("conftest.py") and rx.match("tests/unit/conftest.py"))

    @unittest.skipUnless(HAS_PYTEST, "pytest is not installed")
    def test_c_n1_a_new_fixture_in_a_root_conftest(self):
        for test, want in (("from src.pricing import line_total\n\n\ndef test_bulk(bulk):\n    line_total(*bulk)\n",
                            ("STOPPED", "test-passes-on-base", None)),
                           ("from src.pricing import line_total\n\n\ndef test_bulk(bulk):\n    assert line_total(*bulk) == 9000\n",
                            ("PASSED", "ok", "failed-assertion"))):
            with self.subTest(want=want):
                r = Repo(self, config=PYTEST_CFG, base_files={"conftest.py": CONFTEST})
                code, res, out = r.change({"src/pricing.py": WRONG if want[0] == "STOPPED" else DISCOUNT,
                                           "conftest.py": CONFTEST_HEAD, "tests/test_bulk.py": test})
                self.assertEqual((res["result"], res["cause"]), want[:2], out)
                if want[2]:
                    self.assertEqual(list(res["classes"].values()), [want[2]], out)


class CN2KeptFiles(unittest.TestCase):
    BASE = {"lib/__init__.py": "", "lib/money.py": "def round_cents(value):\n    return int(round(value))\n"}
    HELPER = "def round_cents(value):\n    return int(round(value))\n\n\ndef cents(value):\n    return int(value)\n"

    def test_c_n2_the_hint_names_the_files_the_base_kept(self):
        r = Repo(self, base_files=self.BASE)
        test = test_module("from lib.money import cents\nfrom src.pricing import line_total",
                           "self.assertEqual(cents(line_total(1000, 10)), 9000)")
        code, res, out = r.change({"src/pricing.py": DISCOUNT, "lib/money.py": self.HELPER, "tests/test_bulk.py": test})
        self.assertEqual((res["result"], res["cause"]), ("ERROR", "base-error-unrelated"), out)
        self.assertIn("what to do: The base run kept lib/money.py as on the base; if the tests need the new version there, "
                      "list those files under test_support.", out)

    def test_c_n2_the_downgrade_gets_a_note(self):
        r = Repo(self, base_files=self.BASE)
        test = test_module("import lib.money\nfrom src.pricing import line_total",
                           "self.assertEqual(lib.money.cents(line_total(1000, 10)), 9000)")
        code, res, out = r.change({"src/pricing.py": DISCOUNT, "lib/money.py": self.HELPER, "tests/test_bulk.py": test})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)
        self.assertIn("kept-on-base", res["notes"])

    def test_c_n2_control_no_kept_file_no_change(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": DISCOUNT, "tests/test_bulk.py": TEST_DISCOUNT})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertNotIn("kept-on-base", res["notes"])


class CN3PythonEdits(unittest.TestCase):
    def labels(self, base, head):
        return cg.python_edits(ast.parse(base), ast.parse(head), cg.python_definitions(base)[0], cg.python_definitions(head)[0])

    def test_c_n3_a_type_hint_is_not_an_edit(self):
        for base, head in (("TAX = 21\n", "TAX: int = 21\n"), ("TAX: int = 21\n", "TAX: float = 21\n"),
                           ("class C:\n    TAX = 21\n", "class C:\n    TAX: int = 21\n")):
            with self.subTest(head=head):
                self.assertEqual(self.labels(base, head), [])
        self.assertEqual(self.labels("TAX = 21\n", "TAX: int = 12\n"), ["TAX"])

    def test_c_n3_a_new_assignment_to_an_existing_name_is_an_edit(self):
        self.assertEqual(self.labels("TAX = 21\n", "TAX = 21\nTAX = 30\n"), ["TAX"])
        self.assertEqual(self.labels("class C:\n    TAX = 21\n", "class C:\n    TAX = 21\n    TAX += 1\n"), ["C.TAX"])
        self.assertEqual(self.labels("def f():\n    pass\n", "def f():\n    pass\n\n\nf = staticmethod(f)\n"), ["f"])
        # Controls: a new name, and __all__ gaining names.
        self.assertEqual(self.labels("TAX = 21\n", "TAX = 21\nVAT = 9\n"), [])
        self.assertEqual(self.labels('__all__ = ["a"]\n', '__all__ = ["a"]\n__all__ += ["b"]\n'), [])

    def test_c_n3_the_checker_cases(self):
        base = {"src/pricing.py": "TAX = 21\n\n\ndef line_total(price, qty):\n    return price * qty\n"}
        for head, want in (("TAX: int = 21\n", ("ok-new-code", False)), ("TAX = 21\nTAX = 30\n", ("ok-unproven", True))):
            with self.subTest(head=head):
                r = Repo(self, base_files=base)
                code, res, out = r.change({"src/pricing.py": head + "\n\ndef line_total(price, qty):\n    return price * qty\n" + FORMAT,
                                           "tests/test_format.py": TEST_FORMAT})
                self.assertEqual((res["cause"], "changed-code-unproven" in res["notes"]), want, out)


class CN4BareClone(unittest.TestCase):
    def test_c_n4_a_bare_clone_is_refused_with_a_true_message(self):
        r = Repo(self)
        r.change({"src/pricing.py": DISCOUNT})
        bare = os.path.join(r.root, "bare.git")
        subprocess.run(["git", "clone", "--quiet", "--bare", r.repo, bare], env=ENV, check=True)
        code, res, out = r.run(repo=bare)
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "git", 2), out)
        self.assertIn("is a bare repository, which the guard does not support", res["message"])
        self.assertIn("linked worktree", out)

    def test_c_n4_control_a_folder_that_is_no_repository(self):
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "change_guard.py"), "--repo", d,
                                   "--base", "main", "--head", "HEAD", "--mode", "block", "--log", os.path.join(d, "x.log")],
                                  env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertIn("is not a git repository", proc.stdout.decode())


if __name__ == "__main__":
    unittest.main()
