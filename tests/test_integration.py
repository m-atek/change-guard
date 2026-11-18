# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Integration tests for probe paths the seeded cases do not cover. Demo project, no real data.

Each test builds a throwaway git repository in a temporary folder, runs
change_guard.py on one change, and deletes the folder.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(os.path.dirname(HERE), "change_guard.py")

ENV = dict(os.environ)
ENV.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_AUTHOR_NAME": "Demo Engineer", "GIT_AUTHOR_EMAIL": "demo@example.invalid",
            "GIT_COMMITTER_NAME": "Demo Engineer", "GIT_COMMITTER_EMAIL": "demo@example.invalid"})
for var in ("CHANGE_GUARD_MODE", "CHANGE_GUARD_SKIP_BY", "CHANGE_GUARD_SKIP_REASON", "GITHUB_ACTIONS"):
    ENV.pop(var, None)

PRICING = "def line_total(price, qty):\n    return price * qty\n"
NEW_FN = PRICING + "\n\ndef bulk_total(price, qty):\n    total = price * qty\n    return total * 90 // 100 if qty >= 10 else total\n"
SLOW_WHEN_EMPTY = (
    "import time\nimport unittest\n\nfrom src.pricing import bulk_total\n\n\n"
    "class T(unittest.TestCase):\n    def test_bulk(self):\n        if bulk_total(1000, 10) is None:\n"
    "            time.sleep(30)\n        self.assertTrue(True)\n")
CALLS_ONLY = "import unittest\n\nfrom src.pricing import bulk_total\n\n\nclass T(unittest.TestCase):\n    def test_bulk(self):\n        bulk_total(1000, 10)\n"


class GuardRepo:
    def __init__(self, config):
        self.root = tempfile.mkdtemp(prefix="cg-integration-")
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        self.git("init", "--quiet", "-b", "main")
        base = {"protected": ["src/**"], "tests": ["tests/**/test_*.py"],
                "test_command": "{python} {cg_tools}/cg_unittest_report.py {report} {files}",
                "report_format": "unittest-json"}
        base.update(config)
        self.commit({"src/__init__.py": "", "src/pricing.py": PRICING, "src/widget.js": "export const a = 1;\n",
                     "tests/__init__.py": "", "change-guard.json": json.dumps(base),
                     ".gitignore": ".change-guard/\n__pycache__/\n"})

    def git(self, *args):
        subprocess.run(["git", "-C", self.repo] + list(args), env=ENV, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def commit(self, files):
        for path, text in files.items():
            full = os.path.join(self.repo, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text)
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", "change")

    def run(self, files):
        self.git("checkout", "--quiet", "-B", "change", "main")
        self.commit(files)
        result = os.path.join(self.root, "result.json")
        proc = subprocess.run([sys.executable, GUARD, "--repo", self.repo, "--base", "main", "--head", "change",
                               "--mode", "block", "--log", os.path.join(self.root, "runs.log"), "--result-json", result],
                              env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        with open(result, encoding="utf-8") as fh:
            return proc.returncode, json.load(fh), proc.stdout.decode()

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class ProbePathsTest(unittest.TestCase):
    def guard(self, config):
        g = GuardRepo(config)
        self.addCleanup(g.close)
        return g

    def test_probe_time_box(self):
        g = self.guard({"probe_time_budget_seconds": 2})
        code, res, out = g.run({"src/pricing.py": NEW_FN, "tests/test_bulk.py": SLOW_WHEN_EMPTY})
        self.assertEqual((res["result"], res["cause"], code), ("TIMEOUT", "probe-time-budget", 1), out)

    def test_probe_command_failing_stops(self):
        g = self.guard({"probe": "command", "probe_command": "{python} -c \"import sys; sys.exit(1)\" {functions}"})
        code, res, out = g.run({"src/pricing.py": NEW_FN, "tests/test_bulk.py": CALLS_ONLY})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "probe-passes", 1), out)
        self.assertIn("probe command: exit 1", out)

    def test_probe_command_passing_counts_as_covered(self):
        g = self.guard({"probe": "command", "probe_command": "{python} -c \"import sys; sys.exit(0)\" {functions}"})
        code, res, out = g.run({"src/pricing.py": NEW_FN, "tests/test_bulk.py": CALLS_ONLY})
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok-new-code", 0), out)

    def test_probe_covers_python_beside_another_language(self):
        # Version 0.2.1 (R4): a .js file in the change no longer turns the Python probe off.
        g = self.guard({})
        code, res, out = g.run({"src/pricing.py": NEW_FN, "src/widget.js": "export const a = 2;\nexport function b() { return 1; }\n",
                                "tests/test_bulk.py": CALLS_ONLY})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "probe-passes", 1), out)
        self.assertIn("probe-partial", res["notes"])
        self.assertIn("the probe covered the Python files only; new code in .js files was not probed", out)

    def test_probe_unavailable_for_another_language(self):
        g = self.guard({})
        code, res, out = g.run({"src/widget.js": "export const a = 2;\nexport function b() { return 1; }\n",
                                "tests/test_widget.py": READS_WIDGET})
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)
        self.assertIn("probe-unavailable", res["notes"])
        self.assertIn("the built-in probe covers Python only and this change touches .js files", out)

    def test_generated_files_are_exempt(self):
        # The marker is on the base already: a regenerated file passes untouched.
        g = self.guard({})
        g.commit({"src/pricing_pb.py": "# Code generated by protoc. DO NOT EDIT.\nX = 1\n"})
        code, res, out = g.run({"src/pricing_pb.py": "# Code generated by protoc. DO NOT EDIT.\nX = 2\n"})
        self.assertEqual((res["result"], res["cause"], code), ("EXEMPT", "generated", 0), out)

    def test_added_data_file_is_laid_over_the_base(self):
        files = {"src/pricing.py": BULK, "data/rates.json": '{"bulk_percent": 10}', "tests/test_rates.py": READS_DATA}
        g = self.guard({})
        code, res, out = g.run(files)
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)
        g2 = self.guard({"overlay_added_files": False})
        code, res, out = g2.run(files)
        self.assertEqual(res["classes"], {"tests.test_rates.RatesTest.test_bulk_uses_the_rate_file": "errored-missing-file"}, out)
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)


READS_WIDGET = (
    "import unittest\n\n\nclass WidgetTest(unittest.TestCase):\n    def test_b_is_exported(self):\n"
    "        with open('src/widget.js') as fh:\n            self.assertIn('export function b()', fh.read())\n")
BULK = "def line_total(price, qty):\n    total = price * qty\n    return total * 90 // 100 if qty >= 10 else total\n"
READS_DATA = (
    "import json\nimport unittest\n\nfrom src.pricing import line_total\n\n\n"
    "class RatesTest(unittest.TestCase):\n    def test_bulk_uses_the_rate_file(self):\n"
    "        with open('data/rates.json') as fh:\n            rate = json.load(fh)['bulk_percent']\n"
    "        self.assertEqual(line_total(1000, 10), 10000 * (100 - rate) // 100)\n")


if __name__ == "__main__":
    unittest.main()
