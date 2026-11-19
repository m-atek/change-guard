# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Tests for version 0.3.1: the findings of the 0.3.0 audits (code audit and test audit).

Demo project, no real data. Run from the repository root:
    python3 -m unittest discover -s tests -v

Standard library only. Each test is named after its finding (B1 is in
test_ci_files.py). Every test here fails on 0.3.0 and passes on 0.3.1, except
the ones marked as controls, which hold on both. The javac and node messages
in tests/data/audit-031/ were written by javac 21.0.13 and node 22.18.0 on a
developer Mac (tests/data/audit-031/README.md).
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_v21_fixes import BASE_CFG, ENV, GUARD, PRICING, Repo, cg, test_module  # noqa: E402

DATA = os.path.join(HERE, "data", "audit-031")
DISCOUNT = ("def line_total(price, qty):\n    total = price * qty\n    if qty >= 10:\n"
            "        total = total * 90 // 100\n    return total\n")
FORMAT = '\n\ndef format_price(cents):\n    return "EUR %d.%02d" % (cents // 100, cents % 100)\n'
TEST_DISCOUNT = test_module("from src.pricing import line_total", "self.assertEqual(line_total(1000, 10), 9000)")
TEST_FORMAT = test_module("from src.pricing import format_price", 'self.assertEqual(format_price(1234), "EUR 12.34")')

try:
    import pytest  # noqa: F401
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False


def raw_run(repo, env=None, args=()):
    """The guard without --mode, so the mode comes from the environment or the configuration."""
    e = dict(ENV)
    e.update(env or {})
    with tempfile.TemporaryDirectory() as d:
        result = os.path.join(d, "r.json")
        proc = subprocess.run([sys.executable, GUARD, "--repo", repo, "--base", "main", "--head", "change",
                               "--log", os.path.join(d, "runs.log"), "--result-json", result] + list(args),
                              env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        with open(result, encoding="utf-8") as fh:
            res = json.load(fh)
    return proc.returncode, res, proc.stdout.decode("utf-8", "replace")


def ctx(added=(), added_paths=()):
    c = cg.validate_config(dict(BASE_CFG))
    return {"added": set(added), "added_paths": list(added_paths), "missing_rx": c["_missing_rx"],
            "env_patterns": c["_env_patterns"]}


class I1Mode(unittest.TestCase):
    def setUp(self):
        self.r = Repo(self)
        self.r.git("checkout", "--quiet", "-B", "change", "main")
        self.r.commit({"src/pricing.py": "def line_total(price, qty):\n    return 0\n"})

    def test_i1_case_and_spaces_do_not_matter(self):
        for mode in ("Block", "BLOCK", "block ", " block"):
            with self.subTest(mode=mode):
                code, res, out = raw_run(self.r.repo, env={"CHANGE_GUARD_MODE": mode})
                self.assertEqual((res["result"], res["cause"], res["mode"], code), ("STOPPED", "no-test", "block", 1), out)

    def test_i1_an_unknown_mode_fails_closed(self):
        for mode in ("blocking", "enforce", "on"):
            with self.subTest(mode=mode):
                code, res, out = raw_run(self.r.repo, env={"CHANGE_GUARD_MODE": mode})
                self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
                self.assertIn("fails the check until the value is fixed", res["message"])

    def test_i1_the_mode_key_is_read_the_same_way(self):
        r = Repo(self, config={"mode": "Block"})
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": "def line_total(price, qty):\n    return 0\n"})
        code, res, out = raw_run(r.repo)
        self.assertEqual((res["result"], code), ("STOPPED", 1), out)
        r = Repo(self, config={"mode": "blocking"})
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": "def line_total(price, qty):\n    return 0\n"})
        code, res, out = raw_run(r.repo)
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)

    def test_i1_control_report_still_never_blocks(self):
        code, res, out = raw_run(self.r.repo, env={"CHANGE_GUARD_MODE": "Report"})
        self.assertEqual((res["result"], code), ("STOPPED", 0), out)


class I7Patterns(unittest.TestCase):
    def test_i7_folder_forms_protect_the_folder(self):
        for pattern in ("src/**", "src/", "src", "./src/**", "./src/"):
            with self.subTest(pattern=pattern):
                r = Repo(self, config={"protected": [pattern]})
                code, res, out = r.change({"src/pricing.py": "def line_total(price, qty):\n    return 0\n"})
                self.assertEqual((res["result"], res["cause"]), ("STOPPED", "no-test"), out)

    def test_i7_a_pattern_that_matches_nothing_fails_in_block_mode(self):
        r = Repo(self, config={"protected": ["src/**", "lib/**"]})
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty):\n    return 0\n"})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "config", 2), out)
        self.assertIn("'lib/**'", res["message"])
        code, res, out = r.run(mode="report")
        self.assertEqual((res["result"], code), ("ERROR", 0), out)

    def test_i7_a_folder_deleted_by_the_change_still_counts(self):
        r = Repo(self, config={"protected": ["src/**", "legacy/**"]}, base_files={"legacy/old.py": "X = 1\n"})
        code, res, out = r.change({"legacy/old.py": None})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "no-test"), out)

    def test_i7_glob_rules(self):
        for pattern, path, hit in (("src", "src/a/b.py", True), ("src/", "src/x.py", True), ("./src/**", "src/x.py", True),
                                   ("src", "lib/src/x.py", True), ("src", "srcs/x.py", False), ("*.md", "docs/a.md", True),
                                   ("tests/**/test_*.py", "tests/test_a.py", True), ("src/*.py", "src/sub/a.py", False)):
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(bool(cg.glob_to_regex(pattern).match(path)), hit)


class D2ReportNames(unittest.TestCase):
    def test_d2_a_test_cannot_read_the_phase_from_its_report_name(self):
        r = Repo(self)
        lie = test_module("import os", 'self.assertTrue(os.environ.get("CHANGE_GUARD_REPORT", "").endswith("run-1.jsonl"))')
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty):\n    return price * qty + 999\n",
                                   "tests/test_bulk.py": lie})
        self.assertNotEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertEqual(res["result"], "STOPPED", out)


class D3ParallelRuns(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "the log lock uses fcntl")
    def test_d3_parallel_guards_on_one_checkout_keep_every_line(self):
        r = Repo(self)
        slow = test_module("import time\nfrom src.pricing import line_total", "time.sleep(1)\nself.assertEqual(line_total(-1, 2), 0)")
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": "def line_total(price, qty):\n    return max(0, price * qty)\n", "tests/test_slow.py": slow})
        log = os.path.join(r.repo, ".change-guard", "runs.log")
        results = []

        def run(head):
            e = dict(ENV)
            proc = subprocess.run([sys.executable, GUARD, "--repo", r.repo, "--base", "main", "--head", head, "--mode", "block"],
                                  env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            out = proc.stdout.decode()
            results.append((proc.returncode, [l for l in out.splitlines() if l.startswith("result:")]))

        threads = [threading.Thread(target=run, args=("change",)) for _ in range(4)]
        threads.append(threading.Thread(target=run, args=("main",)))
        for t in threads:
            t.start()
            time.sleep(0.2)
        for t in threads:
            t.join()
        lines = open(log, encoding="utf-8").read().splitlines()
        self.assertEqual(len(lines), 5, results)
        self.assertNotIn("tampered", "".join(lines))
        self.assertEqual(sorted(code for code, _ in results), [0, 0, 0, 0, 0], results)


class D1ChangedBodies(unittest.TestCase):
    def test_d1_an_untested_change_to_an_existing_function_is_not_ok_new_code(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": DISCOUNT + FORMAT, "tests/test_format.py": TEST_FORMAT})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)
        self.assertIn("changed-code-unproven", res["notes"])
        self.assertIn("line_total", res["message"])
        code, res, out = r.run(args=("--config", self.stop_config(r)))
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "base-error-only"), out)

    def stop_config(self, r):
        path = os.path.join(r.root, "stop.json")
        with open(path, "w") as fh:
            json.dump(dict(BASE_CFG, base_error_policy="stop"), fh)
        return path

    def test_d1_control_a_new_function_alone_is_still_ok_new_code(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": PRICING + FORMAT, "tests/test_format.py": TEST_FORMAT})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-new-code"), out)
        self.assertNotIn("changed-code-unproven", res["notes"])

    def test_d1_control_a_tested_change_to_the_existing_function_is_ok(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": DISCOUNT + FORMAT, "tests/test_format.py": TEST_FORMAT,
                                   "tests/test_discount.py": TEST_DISCOUNT})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)

    def test_d1_a_constant_and_a_changed_body_get_the_note(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": DISCOUNT + "\nBULK_LIMIT = 10\n",
                                   "tests/test_c.py": test_module("from src.pricing import BULK_LIMIT", "self.assertTrue(BULK_LIMIT)")})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)
        self.assertIn("changed-code-unproven", res["notes"])

    def test_d1_other_languages_name_the_edited_file(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "-C", d, "init", "-q", "-b", "main"], env=ENV, check=True)
            os.makedirs(os.path.join(d, "src"))
            with open(os.path.join(d, "src", "pricing.js"), "w") as fh:
                fh.write("function total(a, b) {\n  return a * b;\n}\nmodule.exports = { total };\n")
            subprocess.run(["git", "-C", d, "add", "-A"], env=ENV, check=True)
            subprocess.run(["git", "-C", d, "commit", "-qm", "b"], env=ENV, check=True)
            with open(os.path.join(d, "src", "pricing.js"), "w") as fh:
                fh.write("function total(a, b) {\n  return b >= 10 ? a * b * 0.9 : a * b;\n}\n"
                         "function formatPrice(c) {\n  return (c / 100).toFixed(2);\n}\nmodule.exports = { total, formatPrice };\n")
            subprocess.run(["git", "-C", d, "commit", "-qam", "c"], env=ENV, check=True)
            with unittest.mock.patch.dict(os.environ, {k: v for k, v in ENV.items() if k.startswith("GIT_")}):
                diff = cg.diff_by_file(d, "main~1", "main", ["src/pricing.js"])
                modified = []
                names, _ = cg.added_symbols(d, "main~1", "main", [("M", "src/pricing.js")], diff, modified=modified)
        self.assertIn("formatPrice", names)
        self.assertEqual(modified, ["src/pricing.js"])


class I2UnknownNames(unittest.TestCase):
    def test_i2_a_new_dictionary_key_is_not_proof(self):
        base = {"src/rates.py": "RATES = {'nl': 210}\n\n\ndef rate(code):\n    return RATES[code]\n"}
        r = Repo(self, base_files=base)
        code, res, out = r.change({"src/rates.py": "RATES = {'nl': 210, 'de': 190}\n\n\ndef rate(code):\n    return RATES[code]\n",
                                   "tests/test_de.py": test_module("from src import rates", "rates.rate('de')")})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)
        self.assertEqual(set(res["classes"].values()), {"errored-unknown-name"}, out)

    def test_i2_new_class_and_instance_attributes_are_new_names(self):
        base = {"src/cart.py": "class Cart:\n    def __init__(self):\n        self.items = []\n"}
        for head, body in (("class Cart:\n    TAX_RATE = 21\n\n    def __init__(self):\n        self.items = []\n", "Cart.TAX_RATE"),
                           ("class Cart:\n    def __init__(self):\n        self.items = []\n        self.currency = 'EUR'\n", "Cart().currency")):
            with self.subTest(body=body):
                r = Repo(self, base_files=base)
                code, res, out = r.change({"src/cart.py": head, "tests/test_cart.py": test_module("from src.cart import Cart", body)})
                self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)
                self.assertEqual(set(res["classes"].values()), {"errored-new-symbol"}, out)

    def test_i2_a_key_lookup_of_a_new_name_is_new_code(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": PRICING + 'LIMITS = {"bulk": 10}\n',
                                   "tests/test_l.py": test_module("import src.pricing as pricing", 'self.assertTrue(vars(pricing)["LIMITS"])')})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)

    def test_i2_javascript_class_method_and_exported_function(self):
        for message_file, added_line, name in (
                ("node-class-method.txt", "  applyDiscount(pct) {", "applyDiscount"),
                ("node-exports-function.txt", "module.exports.formatPrice = (c) => (c / 100).toFixed(2);", "formatPrice")):
            with self.subTest(name=name):
                with open(os.path.join(DATA, message_file), encoding="utf-8") as fh:
                    message = fh.read().strip()
                found = {m.group(1) for rx in cg.DEFINITION_PATTERNS for m in [rx.match(added_line)] if m} - cg.DEFINITION_KEYWORDS
                self.assertEqual(found, {name})
                record = cg.parse_jest_json(json.dumps({"testResults": [{"name": "t.test.js", "assertionResults": [
                    {"fullName": "a", "status": "failed", "failureMessages": [message]}]}]}))[0]
                head = [cg._rec(record["id"], record["group"], "passed")]
                self.assertEqual(cg.classify_base(head, [record], ctx(added={name}))[record["id"]][0], "errored-new-symbol")
                # Without the name (a form the patterns do not read), it is still never proof.
                cls = cg.classify_base(head, [record], ctx())[record["id"]][0]
                self.assertEqual(cls, "errored-unknown-name")
                self.assertEqual(cg.split_classes({"a": (cls, "")}, cg.validate_config(dict(BASE_CFG)))[0], [])

    def test_i2_control_none_has_no_attribute_is_behaviour(self):
        rec = cg._rec("t.a", "t", "error", "AttributeError", "AttributeError: 'NoneType' object has no attribute 'value'")
        self.assertEqual(cg.classify_base([cg._rec("t.a", "t", "passed")], [rec], ctx())["t.a"][0], "errored-other")


class I3Helpers(unittest.TestCase):
    def test_i3_an_edited_helper_is_laid_over_the_base(self):
        base = {"tests/util.py": "def make_cart():\n    return []\n"}
        util = "def make_cart():\n    return []\n\n\ndef make_order():\n    return (100, 3)\n"
        wrong = "def line_total(price, qty):\n    return price * qty + 1\n"
        for imports, call in (("from tests import util\nfrom src.pricing import line_total", "util.make_order()"),
                              ("from tests.util import make_order\nfrom src.pricing import line_total", "make_order()")):
            with self.subTest(call=call):
                r = Repo(self, base_files=base)
                test = test_module(imports, "self.assertTrue(line_total(*%s) > 0)" % call)
                code, res, out = r.change({"src/pricing.py": wrong, "tests/util.py": util, "tests/test_o.py": test})
                self.assertEqual((res["result"], res["cause"]), ("STOPPED", "test-passes-on-base"), out)


class I4WordLists(unittest.TestCase):
    def test_i4_an_exception_inside_a_test_is_not_an_environment_problem(self):
        base = {"src/db.py": "def query():\n    raise TimeoutError('timed out waiting for db')\n"}
        r = Repo(self, base_files=base)
        code, res, out = r.change({"src/db.py": "def query():\n    return 42\n",
                                   "tests/test_db.py": test_module("from src.db import query", "self.assertEqual(query(), 42)")})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        base = {"src/export.py": "def export(path):\n    return path\n"}
        r = Repo(self, base_files=base)
        code, res, out = r.change({"src/export.py": "def export(path):\n    open(path, 'w').write('x')\n    return path\n",
                                   "tests/test_export.py": test_module("import os, tempfile\nfrom src.export import export",
                                                                       "p = os.path.join(tempfile.mkdtemp(), 'out.txt')\nexport(p)\n"
                                                                       "self.assertEqual(open(p).read(), 'x')")})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)

    @unittest.skipUnless(HAS_PYTEST, "pytest is not installed")
    def test_i4_pytest_assertion_text_is_not_read_for_words(self):
        pyt = {"test_command": "{python} -m pytest -q -p no:cacheprovider --continue-on-collection-errors --junit-xml={report} {files}",
               "report_format": "junit-xml", "inconclusive_exit_codes": [3, 4]}
        for base_src, head_src, test in (
                ("def describe(code):\n    return 'gateway error'\n",
                 "def describe(code):\n    return 'the upstream server timed out' if code == 504 else 'gateway error'\n",
                 "from src.m import describe\n\n\ndef test_504():\n    assert describe(504) == 'the upstream server timed out'\n"),
                ("def describe(name):\n    return name\n",
                 "def describe(name):\n    return None if name == 'root' else name\n",
                 "from src.m import describe\n\n\ndef test_root():\n    found = describe('root')\n    assert not found\n")):
            with self.subTest(test=test[:40]):
                r = Repo(self, config=pyt, base_files={"src/m.py": base_src})
                code, res, out = r.change({"src/m.py": head_src, "tests/test_m.py": test})
                self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)

    def test_i4_pytest_assertion_failure_keeps_its_class(self):
        xml = ('<testsuites><testsuite><testcase classname="tests.test_m" name="test_504">'
               '<failure message="AssertionError: assert \'gateway error\' == \'the upstream...ver timed out\'">x</failure>'
               '</testcase></testsuite></testsuites>')
        rec = cg.parse_junit_xml([xml])[0]
        self.assertEqual((rec["outcome"], rec["type"]), ("failed", "AssertionError"))

    def test_i4_a_new_test_file_in_a_compiler_message_is_not_a_missing_file(self):
        message = ("src/test/java/shop/BulkTest.java:3: error: package org.assertj.core.api does not exist\n"
                   "import static org.assertj.core.api.Assertions.assertThat;")
        err = cg._rec("run:base", "", "error", "no-report", message, True)
        head = [cg._rec("shop.BulkTest.ten", "shop.BulkTest", "passed")]
        # The test file is laid over the base, so it is not among the files missing there.
        self.assertEqual(cg.classify_base(head, [err], ctx(added={"total"}, added_paths=["src/main/java/shop/Pricing.java"]))
                         ["shop.BulkTest.ten"][0], "errored-load")


class I5Declarations(unittest.TestCase):
    """Real javac 21 messages for declaration forms the guard did not read in 0.3.0."""

    def test_i5_class_method_without_access_word_and_constant(self):
        for message_file, added_line, name in (
                ("javac-DiscountTest.txt", "public final class Discount {", "Discount"),
                ("javac-CartTest.txt", "    long withTax(long cents) {", "withTax"),
                ("javac-LimitTest.txt", "    public static final int MAX_QUANTITY = 5;", "MAX_QUANTITY")):
            with self.subTest(name=name):
                found = {m.group(1) for rx in cg.DEFINITION_PATTERNS for m in [rx.match(added_line)] if m} - cg.DEFINITION_KEYWORDS
                self.assertIn(name, found)
                with open(os.path.join(DATA, message_file), encoding="utf-8") as fh:
                    err = cg._rec("run:base", "", "error", "no-report", fh.read(), True)
                head = [cg._rec("shop.T.t", "shop.T", "passed")]
                self.assertEqual(cg.classify_base(head, [err], ctx(added=found))["shop.T.t"][0], "errored-new-symbol")

    def test_i5_control_flow_is_not_a_declaration(self):
        for line in ("    if (quantity >= 10) {", "    } else if (x) {", "        return total(a, b);",
                     "    for (int i = 0; i < n; i++) {", "    while (true) {", "    switch (kind) {"):
            with self.subTest(line=line):
                found = {m.group(1) for rx in cg.DEFINITION_PATTERNS for m in [rx.match(line)] if m} - cg.DEFINITION_KEYWORDS
                self.assertEqual(found, set())


class I6SrcLayout(unittest.TestCase):
    def test_i6_pythonpath_into_the_checkout_is_moved_to_the_worktree(self):
        base = {"src/shop/__init__.py": "", "src/shop/pricing.py": PRICING}
        r = Repo(self, base_files=base)
        test = ("import unittest\nfrom shop.pricing import line_total\n\n\nclass T(unittest.TestCase):\n"
                "    def test_neg(self):\n        self.assertEqual(line_total(-1, 2), 0)\n")
        code, res, out = r.change({"src/shop/pricing.py": "def line_total(price, qty):\n    return max(0, price * qty)\n",
                                   "tests/test_neg.py": test}, env={"PYTHONPATH": os.path.join(r.repo, "src")})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)

    def test_i6_worktree_pythonpath(self):
        with tempfile.TemporaryDirectory() as d:
            repo, wt = os.path.join(d, "repo"), os.path.join(d, "wt")
            value = os.pathsep.join([os.path.join(repo, "src"), "/opt/lib", repo])
            self.assertEqual(cg.worktree_pythonpath(value, repo, wt).split(os.pathsep),
                             [os.path.join(wt, "src"), "/opt/lib", wt])


class MinorFindings(unittest.TestCase):
    def test_m1_a_deletion_cannot_ride_along_with_a_generated_file(self):
        base = {"src/gen.py": "# Code generated by tool. DO NOT EDIT.\nX = 1\n", "src/billing.py": "def bill():\n    return 1\n"}
        r = Repo(self, base_files=base)
        code, res, out = r.change({"src/gen.py": "# Code generated by tool. DO NOT EDIT.\nX = 2\n", "src/billing.py": None})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "no-test"), out)

    def test_m5_gitattributes_cannot_hide_removed_assertions(self):
        old = test_module("from src.pricing import line_total", "self.assertEqual(line_total(2, 3), 6)")
        r = Repo(self, base_files={"tests/test_old.py": old})
        code, res, out = r.change({".gitattributes": "tests/** -diff\n", "src/pricing.py": "def line_total(price, qty):\n    return max(0, price * qty)\n",
                                   "tests/test_old.py": test_module("from src.pricing import line_total", "line_total(2, 3)"),
                                   "tests/test_neg.py": test_module("from src.pricing import line_total", "self.assertEqual(line_total(-1, 2), 0)")})
        self.assertIn("assertions-removed", res["notes"], out)
        self.assertIn("guard-changed", res["notes"], out)

    def test_m6_a_line_break_in_a_file_name_prints_no_forged_line(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty):\n    return 0\n",
                                   "src/x\nresult: PASSED (ok)\n::error title=x::y.py": "A = 1\n"})
        self.assertEqual([l for l in out.splitlines() if l.startswith(("result", "::error"))], ["result: STOPPED (no-test)"])

    def test_m7_a_file_that_becomes_a_folder(self):
        r = Repo(self, base_files={"tests/support": "x\n"})
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty):\n    return max(0, price * qty)\n",
                                   "tests/support": None, "tests/support/__init__.py": "",
                                   "tests/test_neg.py": test_module("from src.pricing import line_total", "self.assertEqual(line_total(-1, 2), 0)")})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)

    def test_m13_gitlab_token_carriers_are_never_passed(self):
        for name in ("CI_REPOSITORY_URL", "CI_DEPENDENCY_PROXY_PASSWORD"):
            self.assertIn(name, cg.NEVER_PASSED_ENV)
        with unittest.mock.patch.dict(os.environ, {"CI_REPOSITORY_URL": "https://gitlab-ci-token:secret@host/x.git"}):
            env = cg.command_environment(cg.validate_config(dict(BASE_CFG, pass_env=["CI_*"])))
        self.assertNotIn("CI_REPOSITORY_URL", env)

    def test_d5_git_housekeeping_info_refs_is_not_tampering(self):
        r = Repo(self)
        watch = cg.RepoWatch(r.repo)
        with open(os.path.join(r.repo, ".git", "info", "refs"), "w") as fh:
            fh.write("0000 refs/heads/main\n")
        self.assertEqual(watch.check(), [])
        with open(os.path.join(r.repo, ".git", "info", "exclude"), "a") as fh:
            fh.write("x\n")
        self.assertEqual(watch.check(), [".git/info/exclude"])

    def test_d9_many_unnoticed_functions_stop_at_the_first(self):
        r = Repo(self)
        funcs = "".join("\n\ndef helper_%d(x):\n    return x + %d\n" % (i, i) for i in range(40))
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty):\n    return max(0, price * qty)\n" + funcs,
                                   "tests/test_neg.py": test_module("from src.pricing import line_total", "self.assertEqual(line_total(-1, 2), 0)")})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "probe-passes"), out)
        self.assertEqual(out.count("with an empty body"), 1, out)
        self.assertLess(len(res["message"]), 400)

    def test_d10_one_long_output_line_is_cut(self):
        lines = cg.tail("x" * 50000 + "\nshort", 5)
        self.assertEqual(lines[1], "short")
        self.assertTrue(lines[0].endswith("[cut]") and len(lines[0]) < 2100)

    def test_d11_a_budget_that_is_not_above_zero_is_refused(self):
        for key in ("time_budget_seconds", "probe_time_budget_seconds"):
            with self.subTest(key=key):
                with self.assertRaises(cg.GuardStop):
                    cg.validate_config(dict(BASE_CFG, **{key: -5}))

    def test_d14_a_folder_that_is_not_a_repository(self):
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run([sys.executable, GUARD, "--repo", d, "--base", "main", "--head", "HEAD", "--mode", "block",
                                   "--log", os.path.join(d, "x.log")], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.stdout.decode()
        self.assertEqual(proc.returncode, 2, out)
        self.assertIn("is not a git repository", out)

    @unittest.skipIf(os.name == "nt", "SIGTERM")
    def test_d12_a_cancelled_run_cleans_up_and_logs(self):
        r = Repo(self)
        slow = test_module("import time\nfrom src.pricing import line_total", "time.sleep(30)\nself.assertEqual(line_total(-1, 2), 0)")
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": "def line_total(price, qty):\n    return max(0, price * qty)\n", "tests/test_slow.py": slow})
        log = os.path.join(r.root, "runs.log")
        proc = subprocess.Popen([sys.executable, GUARD, "--repo", r.repo, "--base", "main", "--head", "change", "--mode", "block",
                                 "--log", log], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(2.5)
        proc.send_signal(signal.SIGTERM)
        out = proc.communicate(timeout=60)[0].decode()
        self.assertEqual(proc.returncode, 2, out)
        self.assertIn("result: ERROR (cancelled)", out)
        self.assertEqual(len(open(log).read().splitlines()), 1)
        self.assertEqual(len(r.git("worktree", "list").strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
