# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Unit tests for the version 0.2.0 logic of change_guard.py. Demo project, no real data.

Run from the repository root:  python3 -m unittest discover -s tests -v
Standard library only. The report samples below are written by hand from each
runner's documentation; only the unittest reporter was run for
real (test_reporter.py).
"""

import json
import os
import sys
import textwrap
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import change_guard as cg  # noqa: E402

BASE_CFG = {
    "protected": ["src/**"],
    "tests": ["tests/**/test_*.py"],
    "test_command": "{python} {cg_tools}/cg_unittest_report.py {report} {files}",
    "report_format": "unittest-json",
}


def cfg(**changes):
    raw = dict(BASE_CFG)
    raw.update(changes)
    return cg.validate_config(raw)


def ctx(added=(), added_paths=(), config=None):
    c = config or cfg()
    return {"added": set(added), "added_paths": list(added_paths),
            "missing_rx": c["_missing_rx"], "env_patterns": c["_env_patterns"]}


def rec(rid, outcome, etype="", message="", group="tests/test_x.py", file_level=False):
    return cg._rec(rid, group, outcome, etype, message, file_level)


class ConfigTest(unittest.TestCase):
    def test_defaults_of_version_2(self):
        c = cfg()
        self.assertEqual(c["base_error_policy"], "probe")
        self.assertEqual(c["probe"], "auto")
        self.assertEqual(c["base_repeats"], 2)
        self.assertEqual(c["head_retries"], 1)
        self.assertEqual(c["mode"], "report")
        self.assertFalse(c["check_edited_tests"])

    def test_version_1_config_still_loads(self):
        c = cg.validate_config({"protected": ["src/**"], "tests": ["tests/**/test_*.py"],
                                "test_command": "{python} -m unittest {files}"})
        self.assertEqual(c["report_format"], "none")

    def test_unknown_key_is_refused(self):
        with self.assertRaises(cg.GuardStop) as ctx_:
            cfg(report_fromat="junit-xml")
        self.assertEqual(ctx_.exception.cause, "config")

    def test_bad_choices_are_refused(self):
        for key, value in (("report_format", "trx"), ("base_error_policy", "ignore"), ("probe", "java"),
                           ("probe_scope", "some"), ("check_edited_tests", "yes"), ("auto_exempt", ["format"]),
                           ("base_repeats", 3), ("head_retries", 2)):
            with self.subTest(key=key):
                with self.assertRaises(cg.GuardStop):
                    cfg(**{key: value})

    def test_report_needs_a_place(self):
        with self.assertRaises(cg.GuardStop):
            cfg(test_command="{python} -m pytest {files}", report_format="junit-xml")
        c = cfg(test_command="./gradlew test {gradle_tests}", report_format="junit-xml",
                report_path="build/test-results/test")
        self.assertEqual(c["report_path"], "build/test-results/test")

    def test_probe_command_needs_a_command(self):
        with self.assertRaises(cg.GuardStop):
            cfg(probe="command")


class ParserTest(unittest.TestCase):
    def test_unittest_json(self):
        text = "\n".join(json.dumps(r) for r in (
            {"id": "load:tests/test_a.py", "file": "tests/test_a.py", "outcome": "error", "type": "ImportError",
             "message": "ImportError: cannot import name 'f'", "file_level": True},
            {"id": "tests.test_b.T.test_x", "file": "tests/test_b.py", "outcome": "failed", "type": "AssertionError",
             "message": "AssertionError: 1 != 2", "file_level": False},
        ))
        out = cg.parse_unittest_json(text)
        self.assertEqual([r["outcome"] for r in out], ["error", "failed"])
        self.assertTrue(out[0]["file_level"])
        self.assertEqual(out[1]["group"], "tests/test_b.py")

    def test_junit_xml_pytest_style(self):
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuites><testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4">
              <testcase classname="" name="tests.test_new" time="0.000">
                <error message="collection failure">ImportError while importing test module
            E   ImportError: cannot import name 'bulk_total' from 'src.pricing'</error>
              </testcase>
              <testcase classname="tests.test_old.TestPrice" name="test_total" time="0.001">
                <failure message="AssertionError: assert 10000 == 9000">assert 10000 == 9000</failure>
              </testcase>
              <testcase classname="tests.test_old.TestPrice" name="test_skip" time="0.000">
                <skipped type="pytest.skip" message="not today"/>
              </testcase>
              <testcase classname="tests.test_old.TestPrice" name="test_ok" time="0.000"/>
            </testsuite></testsuites>
            """)
        out = cg.parse_junit_xml([xml])
        by = {r["id"]: r for r in out}
        self.assertTrue(by["tests.test_new"]["file_level"])
        self.assertEqual(by["tests.test_new"]["group"], "tests.test_new")
        self.assertEqual(by["tests.test_old.TestPrice.test_total"]["outcome"], "failed")
        self.assertEqual(by["tests.test_old.TestPrice.test_skip"]["outcome"], "skipped")
        self.assertEqual(by["tests.test_old.TestPrice.test_ok"]["outcome"], "passed")

    def test_go_json_build_failure_and_results(self):
        events = [
            {"Action": "start", "Package": "shop/price"},
            {"Action": "output", "Package": "shop/price", "Output": "# shop/price [shop/price.test]\n"},
            {"Action": "output", "Package": "shop/price", "Output": "./price_test.go:9:9: undefined: BulkTotal\n"},
            {"Action": "fail", "Package": "shop/price", "FailedBuild": "shop/price [shop/price.test]"},
            {"Action": "run", "Package": "shop/cart", "Test": "TestSum"},
            {"Action": "output", "Package": "shop/cart", "Test": "TestSum", "Output": "    cart_test.go:7: got 3 want 4\n"},
            {"Action": "fail", "Package": "shop/cart", "Test": "TestSum"},
            {"Action": "pass", "Package": "shop/cart", "Test": "TestEmpty"},
        ]
        out = cg.parse_go_json("\n".join(json.dumps(e) for e in events))
        by = {r["id"]: r for r in out}
        self.assertTrue(by["build:shop/price"]["file_level"])
        self.assertIn("undefined: BulkTotal", by["build:shop/price"]["message"])
        self.assertEqual(by["shop/cart/TestSum"]["outcome"], "failed")
        self.assertEqual(by["shop/cart/TestEmpty"]["outcome"], "passed")

    def test_jest_json(self):
        data = {"testResults": [
            {"name": "/repo/src/price.test.ts", "status": "failed", "message": "Cannot find module './bulk'",
             "testExecError": {"message": "Cannot find module './bulk' from 'src/price.test.ts'"},
             "assertionResults": []},
            {"name": "/repo/src/cart.test.ts", "status": "failed", "assertionResults": [
                {"fullName": "cart sums", "status": "failed", "failureMessages": ["TypeError: bulkTotal is not a function"]},
                {"fullName": "cart empty", "status": "passed", "failureMessages": []},
                {"fullName": "cart later", "status": "pending", "failureMessages": []},
            ]},
        ]}
        out = cg.parse_jest_json(json.dumps(data))
        self.assertTrue(out[0]["file_level"])
        self.assertEqual([r["outcome"] for r in out[1:]], ["failed", "passed", "skipped"])

    def test_rspec_json(self):
        data = {"examples": [
            {"id": "./spec/price_spec.rb[1:1]", "status": "failed", "file_path": "./spec/price_spec.rb",
             "exception": {"class": "RSpec::Expectations::ExpectationNotMetError", "message": "expected 9000"}},
            {"id": "./spec/price_spec.rb[1:2]", "status": "failed", "file_path": "./spec/price_spec.rb",
             "exception": {"class": "NoMethodError", "message": "undefined method `bulk_total' for Price"}},
            {"id": "./spec/price_spec.rb[1:3]", "status": "pending", "file_path": "./spec/price_spec.rb"},
        ], "summary": {"errors_outside_of_examples_count": 1},
            "messages": ["An error occurred while loading ./spec/cart_spec.rb"]}
        out = cg.parse_rspec_json(json.dumps(data))
        self.assertEqual([r["outcome"] for r in out], ["failed", "error", "skipped", "error"])
        self.assertTrue(out[-1]["file_level"])

    def test_unreadable_report_is_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "r.xml")
            with open(path, "w") as fh:
                fh.write("<testsuite><testcase")
            self.assertIsNone(cg.read_report("junit-xml", path))
            self.assertIsNone(cg.read_report("junit-xml", os.path.join(d, "missing.xml")))


class ClassifyTest(unittest.TestCase):
    head = [rec("tests.test_x.T.test_a", "passed"), rec("tests.test_x.T.test_b", "passed")]

    def test_import_error_on_a_new_name(self):
        base = [rec("load:tests/test_x.py", "error", "ImportError",
                    "ImportError: cannot import name 'bulk_total' from 'src.pricing'", file_level=True)]
        classes = cg.classify_base(self.head, base, ctx(added={"bulk_total"}))
        self.assertEqual({c for c, _ in classes.values()}, {"errored-new-symbol"})

    def test_import_error_on_an_old_name_is_a_load_error(self):
        base = [rec("load:tests/test_x.py", "error", "ImportError",
                    "ImportError: cannot import name 'helper' from 'src.util'", file_level=True)]
        classes = cg.classify_base(self.head, base, ctx(added={"bulk_total"}))
        self.assertEqual({c for c, _ in classes.values()}, {"errored-load"})

    def test_assertion_and_exception_inside_tests(self):
        base = [rec("tests.test_x.T.test_a", "failed", "AssertionError", "AssertionError: 1 != 2"),
                rec("tests.test_x.T.test_b", "error", "ValueError", "ValueError: quantity")]
        classes = cg.classify_base(self.head, base, ctx())
        self.assertEqual(classes["tests.test_x.T.test_a"][0], "failed-assertion")
        self.assertEqual(classes["tests.test_x.T.test_b"][0], "errored-other")

    def test_jest_style_failure_that_names_a_new_symbol(self):
        head = [rec("cart::sums", "passed", group="src/cart.test.ts")]
        base = [rec("cart::sums", "failed", "", "TypeError: bulkTotal is not a function", group="src/cart.test.ts")]
        classes = cg.classify_base(head, base, ctx(added={"bulkTotal"}))
        self.assertEqual(classes["cart::sums"][0], "errored-new-symbol")

    def test_missing_file_environment_skip_and_not_collected(self):
        head = self.head + [rec("tests.test_x.T.test_c", "passed"), rec("tests.test_y.T.test_d", "passed", group="tests/test_y.py")]
        base = [rec("tests.test_x.T.test_a", "error", "FileNotFoundError",
                    "FileNotFoundError: [Errno 2] No such file or directory: 'src/rates.json'"),
                rec("tests.test_x.T.test_b", "error", "ConnectionRefusedError", "ConnectionRefusedError: Connection refused"),
                rec("tests.test_x.T.test_c", "skipped", "skip")]
        classes = cg.classify_base(head, base, ctx(added_paths=["src/rates.json"]))
        self.assertEqual(classes["tests.test_x.T.test_a"][0], "errored-missing-file")
        # Version 0.3.1 (finding I4 of the 0.3.0 audit): inside a test the environment words are the
        # behaviour under test, so they no longer explain the error; for a load error they still do.
        self.assertEqual(classes["tests.test_x.T.test_b"][0], "errored-other")
        load = [rec("load:tests/test_y.py", "error", "ConnectionRefusedError", "ConnectionRefusedError: Connection refused",
                    group="tests/test_y.py", file_level=True)]
        self.assertEqual(cg.classify_base([rec("tests.test_y.T.test_d", "passed", group="tests/test_y.py")], load, ctx())
                         ["tests.test_y.T.test_d"][0], "errored-environment")
        self.assertEqual(classes["tests.test_x.T.test_c"][0], "skipped")
        self.assertEqual(classes["tests.test_y.T.test_d"][0], "not-collected")

    def test_pytest_collection_error_links_by_module(self):
        head = [rec("tests.test_new.TestBulk.test_ten", "passed", group="tests.test_new.TestBulk"),
                rec("tests.test_old.TestPrice.test_two", "passed", group="tests.test_old.TestPrice")]
        base = [rec("tests.test_new", "error", "", "E   ImportError: cannot import name 'bulk_total'", group="tests.test_new", file_level=True),
                rec("tests.test_old.TestPrice.test_two", "failed", "", "assert 10000 == 9000", group="tests.test_old.TestPrice")]
        classes = cg.classify_base(head, base, ctx(added={"bulk_total"}))
        self.assertEqual(classes["tests.test_new.TestBulk.test_ten"][0], "errored-new-symbol")
        self.assertEqual(classes["tests.test_old.TestPrice.test_two"][0], "failed-assertion")

    def test_missing_symbol_patterns_for_other_languages(self):
        samples = {
            "BulkTotal": "./price_test.go:9:9: undefined: price.BulkTotal",
            "bulkTotal": "Price.java:12: error: cannot find symbol\n    symbol:   method bulkTotal(int,int)",
            "BulkTotal2": "error CS0103: The name 'BulkTotal2' does not exist in the current context",
            "bulk_total": "NoMethodError: undefined method `bulk_total' for an instance of Price",
            "bulkPrice": "Error: Call to undefined function App\\bulkPrice()",
            "bulkTotalSwift": "error: cannot find 'bulkTotalSwift' in scope",
            "newHelper": "SyntaxError: The requested module './price.js' does not provide an export named 'newHelper'",
        }
        c = cfg()
        for name, message in samples.items():
            with self.subTest(name=name):
                self.assertEqual(cg.missing_symbol_name(message, {name}, c["_missing_rx"]), name)
        self.assertIsNone(cg.missing_symbol_name("undefined: Other", {"BulkTotal"}, c["_missing_rx"]))


class DecisionTest(unittest.TestCase):
    def test_all_passed_on_base_is_stopped(self):
        stop = cg.first_decision({"a": ("passed", ""), "b": ("skipped", "")}, cfg())
        self.assertEqual((stop.result, stop.cause), ("STOPPED", "test-passes-on-base"))

    def test_only_unrelated_errors_is_an_error(self):
        stop = cg.first_decision({"a": ("errored-load", "SyntaxError: bad"), "b": ("passed", "")}, cfg())
        self.assertEqual((stop.result, stop.cause), ("ERROR", "base-error-unrelated"))
        self.assertIn("SyntaxError: bad", stop.message)

    def test_continue_when_there_is_proof_or_new_code(self):
        self.assertIsNone(cg.first_decision({"a": ("failed-assertion", "")}, cfg()))
        self.assertIsNone(cg.first_decision({"a": ("errored-new-symbol", "")}, cfg()))

    def test_errored_other_counts_only_when_allowed(self):
        classes = {"a": ("errored-other", "ValueError")}
        self.assertEqual(cg.split_classes(classes, cfg())[0], ["a"])
        strict = cfg(errored_counts_as_proof=False)
        self.assertEqual(cg.split_classes(classes, strict), ([], [], ["a"]))
        self.assertEqual(cg.first_decision(classes, strict).cause, "base-error-unrelated")

    def test_final_verdicts(self):
        c = cfg()
        self.assertEqual(cg.final_decision(["a"], [], "none", c).cause, "ok")
        self.assertEqual(cg.final_decision(["a"], [], "none", c, has_report=False).message, cg.MESSAGES["ok-exit-code"])
        self.assertEqual(cg.final_decision([], ["a"], "covered", c).cause, "ok-new-code")
        self.assertEqual(cg.final_decision([], ["a"], "none", c).cause, "ok-unproven")
        self.assertEqual(cg.final_decision([], ["a"], "none", cfg(base_error_policy="note")).cause, "ok-unproven")
        stop = cg.final_decision([], ["a"], "none", cfg(base_error_policy="stop"))
        self.assertEqual((stop.result, stop.cause), ("STOPPED", "base-error-only"))

    def test_every_message_is_one_sentence_without_dashes(self):
        for key, text in cg.MESSAGES.items():
            with self.subTest(key=key):
                self.assertTrue(text.endswith("."))
                self.assertEqual(text.count(". "), 0)
                self.assertNotIn(chr(0x2014), text)
                self.assertNotIn(chr(0x2013), text)


class ProbeTest(unittest.TestCase):
    SOURCE = textwrap.dedent('''\
        """Demo module."""


        def old(x):
            return x


        def bulk_total(price, qty):
            """Ten percent off from ten items."""
            total = price * qty
            if qty >= 10:
                total = total * 90 // 100
            return total


        def inline(x): return x * 2


        class Cart:
            def add(self, item):
                self.items = [item]
                return len(self.items)

            def only_doc(self):
                """Nothing else."""
        ''')

    def run_module(self, source):
        namespace = {}
        exec(compile(source, "<test>", "exec"), namespace)
        return namespace

    def test_definitions(self):
        funcs, names = cg.python_definitions(self.SOURCE)
        self.assertEqual(sorted(funcs), ["Cart.add", "Cart.only_doc", "bulk_total", "inline", "old"])
        self.assertIn("Cart", names)

    def test_neutral_bodies(self):
        new = cg.neutralise_python(self.SOURCE, ["bulk_total", "inline", "Cart.add", "Cart.only_doc"])
        ns = self.run_module(new)
        self.assertIsNone(ns["bulk_total"](1000, 10))
        self.assertIsNone(ns["inline"](3))
        self.assertIsNone(ns["Cart"]().add("x"))
        self.assertEqual(ns["old"](5), 5)
        self.assertEqual(ns["bulk_total"].__doc__, "Ten percent off from ten items.")

    def test_unknown_function_raises(self):
        with self.assertRaises(KeyError):
            cg.neutralise_python(self.SOURCE, ["missing"])

    def test_targets_respect_the_ignore_list(self):
        targets = cg.probe_targets({"src/a.py": ["f", "C.__repr__", "_log_call", "C.g"]}, cfg())
        self.assertEqual(targets, [("src/a.py", "f"), ("src/a.py", "C.g")])

    def test_sub_budget_ends_on_its_own_limit(self):
        parent = cg.Budget(100)
        sub = cg.SubBudget(0.01, parent)
        time.sleep(0.02)
        with self.assertRaises(cg.BudgetExceeded) as exc:
            sub.remaining("probe")
        self.assertEqual(exc.exception.phase, "probe-own")


class NotesTest(unittest.TestCase):
    def test_notes_from_a_test_diff(self):
        diff = {
            "tests/test_old.py": {"removed": ["        self.assertEqual(f(1), 2)", "    def test_gone(self):"],
                                  "added": ["        f(1)"]},
            "tests/test_new.py": {"removed": [],
                                  "added": ["    @unittest.skip('later')",
                                            "        with mock.patch.object(pricing, 'bulk_total', return_value=1):"]},
        }
        notes = cg.test_diff_notes(diff, ["tests/test_old.py"], ["tests/test_dead.py"], ["tests/test_new.py"],
                                   {"bulk_total"}, ["tests/__snapshots__/a.snap"], ["src/a.py"])
        codes = [c for c, _ in notes]
        for expected in ("assertions-removed", "test-deleted", "skip-marker-added", "mocks-new-code", "snapshot-changed"):
            self.assertIn(expected, codes)
        self.assertEqual(codes.count("test-deleted"), 2)

    def test_no_note_for_an_ordinary_edit(self):
        diff = {"tests/test_old.py": {"removed": ["        self.assertEqual(f(1), 2)"],
                                      "added": ["        self.assertEqual(f(1), 3)"]}}
        self.assertEqual(cg.test_diff_notes(diff, ["tests/test_old.py"], [], [], set(), [], ["src/a.py"]), [])


class OutputTest(unittest.TestCase):
    def test_log_line_has_19_columns_and_keeps_cg1_order(self):
        state = {"base": "a" * 40, "head": "b" * 40, "protected_files": 1, "test_files": 1,
                 "counts": (1, 0, 0), "probe": "covered", "notes": [("passes-on-base", "x")]}
        outcome = cg.GuardStop("PASSED", "ok", "Tab\tinside.")
        fields = cg.log_line(state, outcome, "block", "pr-1", 1.5).split("\t")
        self.assertEqual(len(fields), 19)
        self.assertEqual(len(cg.LOG_COLUMNS), 19)
        self.assertEqual(fields[0], "cg2")
        self.assertEqual(fields[2:6], ["PASSED", "ok", "block", "pr-1"])
        self.assertEqual(fields[13], "Tab inside.")
        self.assertEqual(fields[14:], ["1", "0", "0", "covered", "passes-on-base"])

    def test_expand_command_fills_report_and_tools(self):
        cmd = cg.expand_command("{python} {cg_tools}/cg_unittest_report.py {report} {files}", ["tests/test_a.py"], "/tmp/r 1.jsonl")
        self.assertIn("'/tmp/r 1.jsonl'", cmd)
        self.assertIn("cg_unittest_report.py", cmd)
        self.assertTrue(cmd.endswith("tests/test_a.py"))

    def test_glob_rules_unchanged(self):
        rx = cg.glob_to_regex("tests/**/test_*.py")
        self.assertTrue(rx.match("tests/test_a.py"))
        self.assertTrue(rx.match("tests/unit/test_a.py"))
        self.assertFalse(rx.match("src/test_a.py"))
        self.assertTrue(cg.glob_to_regex("*.md").match("docs/a/README.md"))


if __name__ == "__main__":
    unittest.main()
