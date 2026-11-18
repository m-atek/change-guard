# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Unit tests for the pytest fixes P1 to P4 (see CHANGELOG.md). Demo project, no real data.

Run from the repository root:  python3 -m unittest discover -s tests -v
Standard library only. The XML below is the shape pytest 9.2.0 really wrote on
17 November 2026 (junit_family xunit2), with the temporary paths shortened.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import change_guard as cg  # noqa: E402

BASE_CFG = {
    "protected": ["src/**"],
    "tests": ["tests/**/test_*.py"],
    "test_command": "{python} -m pytest -q --junitxml={report} {files}",
    "report_format": "junit-xml",
}


def cfg(**changes):
    raw = dict(BASE_CFG)
    raw.update(changes)
    return cg.validate_config(raw)


def ctx(added=(), config=None):
    c = config or cfg()
    return {"added": set(added), "added_paths": [], "missing_rx": c["_missing_rx"], "env_patterns": c["_env_patterns"]}


# Real pytest 9.2.0 output: a collection error for one file, an ordinary
# assertion, an exception in the test body and a NameError, all without a type.
PYTEST_XML = """<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest" errors="1" failures="3" skipped="0" tests="5">
<testcase classname="" name="tests.test_shipping" time="0.000"><error message="collection failure">ImportError while importing test module '/tmp/base/tests/test_shipping.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
tests/test_shipping.py:1: in &lt;module&gt;
    from src.shipping import shipping_cents
E   ModuleNotFoundError: No module named 'src.shipping'</error></testcase>
<testcase classname="tests.test_bulk" name="test_bulk_discount[10-9000]" time="0.000"><failure message="assert 10000 == 9000&#10; +  where 10000 = line_total(1000, 10)">quantity = 10, expected = 9000
E       assert 10000 == 9000
tests/test_bulk.py:8: AssertionError</failure></testcase>
<testcase classname="tests.test_large" name="test_hundred_items" time="0.000"><failure message="OverflowError: too many items">src/pricing.py:8: in line_total
E   OverflowError: too many items</failure></testcase>
<testcase classname="tests.test_star" name="test_bulk_total" time="0.000"><failure message="NameError: name 'bulk_total' is not defined">E   NameError: name 'bulk_total' is not defined</failure></testcase>
</testsuite></testsuites>"""


class PytestJunitTest(unittest.TestCase):
    def records(self):
        return {r["id"]: r for r in cg.parse_junit_xml([PYTEST_XML])}

    def test_p1_empty_report_is_not_a_head_failure(self):
        # pytest exit 5 with an empty report: no-test-collected decides, not test-fails-on-head.
        self.assertFalse(cg.head_failures({"rc": 5, "records": []}))
        self.assertTrue(cg.head_failures({"rc": 1, "records": [cg._rec("t", "g", "failed")]}))
        self.assertTrue(cg.head_failures({"rc": 2, "records": [cg._rec("m", "", "error", file_level=True)]}))
        self.assertTrue(cg.head_failures({"rc": 1, "records": None}))

    def test_p2_collection_error_links_only_its_own_file(self):
        recs = list(self.records().values())
        head = [cg._rec("tests.test_shipping.test_free", "tests.test_shipping", "passed"),
                cg._rec("tests.test_other.test_x", "tests.test_other", "passed")]
        classes = cg.classify_base(head, recs, ctx(added={"src.shipping", "shipping", "shipping_cents"}))
        self.assertEqual(classes["tests.test_shipping.test_free"][0], "errored-new-symbol")
        # A test of another file that pytest did not run is not linked to that error.
        self.assertEqual(classes["tests.test_other.test_x"][0], "not-collected")
        # A load error that names no file (no report at all) still covers every test.
        run_err = [cg._rec("run:base", "", "error", "no-report", "SyntaxError: bad", True)]
        self.assertEqual(cg.classify_base(head, run_err, ctx())["tests.test_other.test_x"][0], "errored-load")

    def test_p3_exception_in_a_pytest_failure_is_an_error(self):
        r = self.records()
        self.assertEqual(r["tests.test_bulk.test_bulk_discount[10-9000]"]["outcome"], "failed")
        self.assertEqual(r["tests.test_large.test_hundred_items"]["outcome"], "error")
        self.assertEqual(r["tests.test_large.test_hundred_items"]["type"], "OverflowError")
        head = [cg._rec(t, "", "passed") for t in r if not r[t]["file_level"]]
        classes = cg.classify_base(head, list(r.values()), ctx(added={"bulk_total"}))
        self.assertEqual(classes["tests.test_bulk.test_bulk_discount[10-9000]"][0], "failed-assertion")
        self.assertEqual(classes["tests.test_large.test_hundred_items"][0], "errored-other")
        self.assertEqual(classes["tests.test_star.test_bulk_total"][0], "errored-new-symbol")
        strict = cfg(errored_counts_as_proof=False)
        proof, new, other = cg.split_classes(classes, strict)
        self.assertEqual(proof, ["tests.test_bulk.test_bulk_discount[10-9000]"])
        self.assertIn("tests.test_large.test_hundred_items", other)
        # A failure that already has a type (Gradle, Surefire) is left alone.
        typed = cg.parse_junit_xml(['<testsuite><testcase classname="A" name="t"><failure type="java.lang.IllegalStateException" message="IllegalStateException: x"/></testcase></testsuite>'])
        self.assertEqual(typed[0]["outcome"], "failed")

    def test_p4_first_line_reads_pytest_error_lines(self):
        err = cg._rec("tests.test_bulk", "tests.test_bulk", "error", "",
                      "collection failure\ntests/test_bulk.py:3: in <module>\n    from src.pricing import line_total\n"
                      "E     File \"/tmp/base/src/__init__.py\", line 1\nE       VERSION = (\nE               ^\n"
                      "E   SyntaxError: '(' was never closed", True)
        self.assertEqual(cg.first_line(err), "SyntaxError: '(' was never closed")
        shipping = self.records()["tests.test_shipping"]
        self.assertEqual(cg.first_line(shipping), "ModuleNotFoundError: No module named 'src.shipping'")


if __name__ == "__main__":
    unittest.main()
