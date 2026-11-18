# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Unit tests for cg_unittest_report.py, run for real in a temporary folder. Demo project, no real data."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTER = os.path.join(os.path.dirname(HERE), "cg_unittest_report.py")

FILES = {
    "pkg/__init__.py": "",
    "pkg/calc.py": "def double(x):\n    return 2 * x\n",
    "tests/__init__.py": "",
    "tests/test_mixed.py": textwrap.dedent("""\
        import unittest

        from pkg.calc import double


        class MixedTest(unittest.TestCase):
            def test_pass(self):
                self.assertEqual(double(2), 4)

            def test_fail(self):
                self.assertEqual(double(2), 5)

            def test_error(self):
                raise ValueError("old code raises")

            @unittest.skip("not today")
            def test_skip(self):
                pass

            @unittest.expectedFailure
            def test_xfail(self):
                self.assertEqual(double(2), 5)

            def test_subtests(self):
                for n in (1, 2):
                    with self.subTest(n=n):
                        self.assertEqual(double(n), 2)
        """),
    "tests/test_broken.py": "from pkg.calc import triple\n",
    "tests/test_syntax.py": "def oops(:\n",
}


class ReporterTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cg-reporter-test-")
        for path, text in FILES.items():
            full = os.path.join(self.root, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text)
        self.report = os.path.join(self.root, "report.jsonl")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_reporter(self, *files):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([sys.executable, REPORTER, self.report] + list(files), cwd=self.root, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        with open(self.report, encoding="utf-8") as fh:
            records = [json.loads(l) for l in fh if l.strip()]
        return proc.returncode, proc.stdout.decode(), {r["id"]: r for r in records}

    def test_outcomes_per_test(self):
        rc, out, by = self.run_reporter("tests/test_mixed.py")
        self.assertEqual(rc, 1)
        prefix = "tests.test_mixed.MixedTest."
        self.assertEqual(by[prefix + "test_pass"]["outcome"], "passed")
        self.assertEqual(by[prefix + "test_fail"]["outcome"], "failed")
        self.assertEqual(by[prefix + "test_fail"]["type"], "AssertionError")
        self.assertEqual(by[prefix + "test_error"]["outcome"], "error")
        self.assertEqual(by[prefix + "test_error"]["type"], "ValueError")
        self.assertEqual(by[prefix + "test_skip"]["outcome"], "skipped")
        self.assertEqual(by[prefix + "test_xfail"]["type"], "expected-failure")
        self.assertEqual(by[prefix + "test_subtests"]["outcome"], "failed")
        self.assertTrue(all(r["file"] == "tests/test_mixed.py" for r in by.values()))
        self.assertIn("Ran 6 tests", out)

    def test_load_errors_are_file_level(self):
        rc, out, by = self.run_reporter("tests/test_broken.py", "tests/test_syntax.py")
        self.assertEqual(rc, 1)
        broken = by["load:tests/test_broken.py"]
        self.assertTrue(broken["file_level"])
        self.assertEqual(broken["type"], "ImportError")
        self.assertIn("cannot import name 'triple'", broken["message"])
        self.assertEqual(by["load:tests/test_syntax.py"]["type"], "SyntaxError")

    def test_all_passing_exits_zero(self):
        with open(os.path.join(self.root, "tests", "test_ok.py"), "w") as fh:
            fh.write("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
        rc, _, by = self.run_reporter("tests/test_ok.py")
        self.assertEqual(rc, 0)
        self.assertEqual(list(by.values())[0]["outcome"], "passed")


if __name__ == "__main__":
    unittest.main()
