# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Tests for version 0.3.0: report parsers and missing-symbol patterns on real runner output.

Demo project, no real data. Run from the repository root:
    python3 -m unittest discover -s tests -v

Standard library only. The files in tests/data/polyglot/ were written by the
real runners on GitHub's hosted Linux runner (image ubuntu-26.04, 18 November
2026, run 44335953379 of the polyglot workflow) for the fixtures in
tests/polyglot/: Vitest 3.2.4, Jest 29.7.0, go test (Go 1.27.4), Maven 3.9.15
with Surefire 3.5.2 and JUnit 5.11.4, dotnet test (SDK 11.0.100, xUnit 2.9.3,
TRX logger), PHPUnit 11.5.58 and RSpec 3.13. tests/data/polyglot/README.md
says what was changed in them (only the worktree folder, shown as <worktree>).
"""

import difflib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_v21_fixes import BASE_CFG, Repo, cg, test_module  # noqa: E402

DATA = os.path.join(HERE, "data", "polyglot")
FIXTURES = os.path.join(HERE, "polyglot")
HEAD_DIR = "/tmp/cg-polyglot/wt-11"
BASE_DIR = "/tmp/cg-polyglot/wt-12"

# Ecosystem: (report_format, protected source of the fixture, how its report is stored)
ECOSYSTEMS = {
    "vitest": ("jest-json", "src/pricing.ts", "file"),
    "jest": ("jest-json", "src/pricing.js", "file"),
    "go": ("go-json", "shop/pricing.go", "file"),
    "maven": ("junit-xml", "src/main/java/shop/Pricing.java", "folder"),
    "dotnet": ("dotnet-trx", "src/Shop/Pricing.cs", "folder"),
    "phpunit": ("junit-xml", "src/Pricing.php", "file"),
    "rspec": ("rspec-json", "lib/shop/pricing.rb", "file"),
    # Added on 18 November 2026 from run 44343395672 (Gradle 9.9.1 on Java 21.0.13,
    # Kotlin 2.4.21, Swift 6.4.2 on Linux).
    "gradle": ("junit-xml", "src/main/java/shop/Pricing.java", "folder"),
    "kotlin": ("junit-xml", "src/main/kotlin/shop/Pricing.kt", "folder"),
    "swift": ("junit-xml", "Sources/Shop/Pricing.swift", "folder"),
    "swift-testing": ("junit-xml", "Sources/Shop/Pricing.swift", "folder"),
}
# Runners that write no report when the tests do not compile on the base.
NO_REPORT_WHEN_NOT_COMPILED = ("maven", "dotnet", "gradle", "kotlin", "swift", "swift-testing")


# The report format of every fixture in tests/polyglot/.
FORMATS = dict({eco: v[0] for eco, v in ECOSYSTEMS.items()},
               gradle="junit-xml", kotlin="junit-xml", swift="junit-xml", **{"swift-testing": "junit-xml"})


def config():
    return cg.validate_config(dict(BASE_CFG))


def ctx(added):
    c = config()
    return {"added": set(added), "added_paths": [], "missing_rx": c["_missing_rx"], "env_patterns": c["_env_patterns"]}


def added_names(eco, case):
    """Names the change adds, found the way the guard finds them outside Python (DEFINITION_PATTERNS on added lines)."""
    source = ECOSYSTEMS[eco][1]
    with open(os.path.join(FIXTURES, eco, "base", *source.split("/")), encoding="utf-8") as fh:
        old = fh.read().splitlines()
    with open(os.path.join(FIXTURES, eco, "changes", case, *source.split("/")), encoding="utf-8") as fh:
        new = fh.read().splitlines()
    names = set()
    for line in difflib.ndiff(old, new):
        if line.startswith("+ "):
            for rx in cg.DEFINITION_PATTERNS:
                m = rx.match(line[2:])
                if m:
                    names.add(m.group(1))
    return names


def data_files(eco, case, phase):
    folder = os.path.join(DATA, eco)
    prefix = "%s-%s" % (case, phase)
    return sorted(os.path.join(folder, n) for n in os.listdir(folder)
                  if n.startswith(prefix) and not n.endswith("-output.txt"))


def read_real(test, eco, case, phase, workdir):
    """Write a captured report back under a worktree-like folder and read it the way run_tests does."""
    fmt, _, kind = ECOSYSTEMS[eco]
    root = tempfile.mkdtemp(prefix="cg-polyglot-")
    test.addCleanup(shutil.rmtree, root, True)
    files = data_files(eco, case, phase)
    test.assertTrue(files, "no captured report for %s %s %s" % (eco, case, phase))
    if kind == "folder":
        path = os.path.join(root, "reports")
        os.makedirs(path)
        targets = [os.path.join(path, os.path.basename(f)) for f in files]
    else:
        path = os.path.join(root, "report" + os.path.splitext(files[0])[1])
        targets = [path]
    for src, dst in zip(files, targets):
        with open(src, encoding="utf-8") as fh:
            text = fh.read().replace("<worktree>", workdir)
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(text)
    return cg.relative_records(cg.read_report(fmt, path), workdir)


def base_output_record(eco, case):
    """The guard's record for a base run that wrote no report: the end of the output as one load error."""
    with open(os.path.join(DATA, eco, "%s-base-output.txt" % case), encoding="utf-8") as fh:
        text = fh.read().replace("<worktree>", BASE_DIR)
    return [cg._rec("run:base", "", "error", "no-report", "\n".join(text.rstrip().splitlines()[-40:]), True)]


class RealReportsAreRead(unittest.TestCase):
    """Every parser reads its runner's real report, and head and base ids match across worktrees."""

    def test_head_reports_have_passing_tests_with_relative_ids(self):
        for eco in ECOSYSTEMS:
            for case in ("3-real-test", "4-new-function-call-only"):
                with self.subTest(eco=eco, case=case):
                    head = read_real(self, eco, case, "head", HEAD_DIR)
                    self.assertIsNotNone(head)
                    passed = [r for r in head if r["outcome"] == "passed" and not r["file_level"]]
                    self.assertTrue(passed)
                    for r in head:
                        self.assertNotIn(HEAD_DIR, r["id"])
                        self.assertNotIn(HEAD_DIR, r["group"])

    def test_case_3_new_test_fails_by_assertion_on_the_base(self):
        for eco in ECOSYSTEMS:
            with self.subTest(eco=eco):
                head = read_real(self, eco, "3-real-test", "head", HEAD_DIR)
                base = read_real(self, eco, "3-real-test", "base", BASE_DIR)
                head_passed = [r for r in head if r["outcome"] == "passed" and not r["file_level"]]
                classes = cg.classify_base(head_passed, base, ctx(added_names(eco, "3-real-test")))
                values = sorted(c for c, _ in classes.values())
                self.assertEqual(values.count("failed-assertion"), 1, classes)
                self.assertEqual(set(values) - {"failed-assertion"}, {"passed"}, classes)
                stop = cg.first_decision(classes, config())
                self.assertIsNone(stop)
                proof, new, _ = cg.split_classes(classes, config())
                self.assertEqual((len(proof), len(new)), (1, 0))

    def test_case_4_new_function_is_new_code_not_proof(self):
        for eco in ECOSYSTEMS:
            with self.subTest(eco=eco):
                head = read_real(self, eco, "4-new-function-call-only", "head", HEAD_DIR)
                if eco in NO_REPORT_WHEN_NOT_COMPILED:
                    # The test does not compile on the base, so the runner writes no report.
                    base = base_output_record(eco, "4-new-function-call-only")
                else:
                    base = read_real(self, eco, "4-new-function-call-only", "base", BASE_DIR)
                head_passed = [r for r in head if r["outcome"] == "passed" and not r["file_level"]]
                added = added_names(eco, "4-new-function-call-only")
                self.assertTrue({"formatPrice", "FormatPrice", "format_price"} & added, added)
                classes = cg.classify_base(head_passed, base, ctx(added))
                self.assertEqual({c for c, _ in classes.values()}, {"errored-new-symbol"}, classes)
                proof, new, _ = cg.split_classes(classes, config())
                self.assertEqual(proof, [])
                verdict = cg.final_decision(proof, new, "none", config())
                self.assertEqual((verdict.result, verdict.cause), ("PASSED", "ok-unproven"))
                stop = cg.final_decision(proof, new, "none", cg.validate_config(dict(BASE_CFG, base_error_policy="stop")))
                self.assertEqual((stop.result, stop.cause), ("STOPPED", "base-error-only"))

    def test_without_relative_ids_jest_and_vitest_tests_would_not_match(self):
        # The defect 0.3.0 fixes: these runners name a test by the absolute path of its file.
        for eco in ("vitest", "jest"):
            with self.subTest(eco=eco):
                with open(data_files(eco, "3-real-test", "head")[0], encoding="utf-8") as fh:
                    head_raw = cg.parse_jest_json(fh.read().replace("<worktree>", HEAD_DIR))
                with open(data_files(eco, "3-real-test", "base")[0], encoding="utf-8") as fh:
                    base_raw = cg.parse_jest_json(fh.read().replace("<worktree>", BASE_DIR))
                self.assertFalse({r["id"] for r in head_raw} & {r["id"] for r in base_raw})
                head = cg.relative_records(head_raw, HEAD_DIR)
                base = cg.relative_records(base_raw, BASE_DIR)
                self.assertEqual({r["id"] for r in head}, {r["id"] for r in base})
                self.assertTrue(all(r["id"].startswith("tests/bulk.test.") for r in head))


class RealMissingSymbolMessages(unittest.TestCase):
    """The missing-symbol patterns against the compilers' and runtimes' real messages."""

    def message(self, eco, case="4-new-function-call-only"):
        if eco in NO_REPORT_WHEN_NOT_COMPILED:
            return base_output_record(eco, case)[0]["message"]
        base = read_real(self, eco, case, "base", BASE_DIR)
        return "\n".join(r["type"] + ": " + r["message"] for r in base if r["outcome"] in ("failed", "error"))

    def test_each_runner_names_the_new_function(self):
        expected = {"vitest": "formatPrice", "jest": "formatPrice", "go": "FormatPrice", "maven": "formatPrice",
                    "dotnet": "FormatPrice", "phpunit": "formatPrice", "rspec": "format_price",
                    "gradle": "formatPrice", "kotlin": "formatPrice", "swift": "formatPrice",
                    "swift-testing": "formatPrice"}
        rx = config()["_missing_rx"]
        for eco, name in expected.items():
            with self.subTest(eco=eco):
                self.assertEqual(cg.missing_symbol_name(self.message(eco), {name}, rx), name)
                self.assertIsNone(cg.missing_symbol_name(self.message(eco), {"somethingElse"}, rx))

    def test_vitest_message_did_not_match_the_patterns_of_0_2_2(self):
        text = self.message("vitest")
        self.assertIn("(0 , formatPrice) is not a function", text)
        self.assertIsNone(re.search(r"(\w+) is not a function", text.replace("(0 , formatPrice)", "")))
        self.assertIsNone(re.compile(r"(\w+) is not a function").search("(0 , formatPrice) is not a function"))

    def test_the_detail_names_the_compiler_error(self):
        for eco, needle in (("maven", "symbol: method formatPrice(int)"), ("dotnet", "error CS0117"),
                            ("go", "undefined: FormatPrice"), ("gradle", "symbol: method formatPrice(int)"),
                            ("kotlin", "Unresolved reference 'formatPrice'"),
                            ("swift", "error: type 'Pricing' has no member 'formatPrice'"),
                            ("swift-testing", "error: type 'Pricing' has no member 'formatPrice'")):
            with self.subTest(eco=eco):
                if eco == "go":
                    base = read_real(self, eco, "4-new-function-call-only", "base", BASE_DIR)
                else:
                    base = base_output_record(eco, "4-new-function-call-only")
                head = read_real(self, eco, "4-new-function-call-only", "head", HEAD_DIR)
                self.assertNotIn("\x1b", "".join(d for _, d in cg.classify_base(
                    [r for r in head if r["outcome"] == "passed"], base, ctx(added_names(eco, "4-new-function-call-only"))).values()))
                head_passed = [r for r in head if r["outcome"] == "passed" and not r["file_level"]]
                classes = cg.classify_base(head_passed, base, ctx(added_names(eco, "4-new-function-call-only")))
                for cls, detail in classes.values():
                    self.assertIn(needle, detail)


class JestAndVitestErrorTypes(unittest.TestCase):
    def failure(self, eco, case):
        with open(data_files(eco, case, "base")[0], encoding="utf-8") as fh:
            data = json.load(fh)
        for suite in data["testResults"]:
            for a in suite["assertionResults"]:
                if a["status"] == "failed":
                    return "\n".join(a["failureMessages"])
        self.fail("no failure in %s %s" % (eco, case))

    def test_real_messages_give_the_error_class(self):
        self.assertEqual(cg.js_error_type(self.failure("jest", "3-real-test")), "JestAssertionError")
        self.assertEqual(cg.js_error_type(self.failure("vitest", "3-real-test")), "AssertionError")
        self.assertEqual(cg.js_error_type(self.failure("jest", "4-new-function-call-only")), "TypeError")
        self.assertEqual(cg.js_error_type(self.failure("vitest", "4-new-function-call-only")), "TypeError")
        self.assertEqual(cg.js_error_type("no class here"), "")

    def test_an_unexplained_type_error_is_an_exception_not_an_assertion(self):
        head = [cg._rec("t::a", "tests/a.test.js", "passed")]
        base = cg.parse_jest_json(json.dumps({"testResults": [{"name": "tests/a.test.js", "assertionResults": [
            {"fullName": "a", "status": "failed", "failureMessages": ["TypeError: Cannot read properties of undefined"]}]}]}))
        base[0]["id"] = "t::a"
        classes = cg.classify_base(head, base, ctx(set()))
        self.assertEqual(classes["t::a"][0], "errored-other")
        no_proof = cg.validate_config(dict(BASE_CFG, errored_counts_as_proof=False))
        self.assertEqual(cg.split_classes(classes, no_proof)[0], [])


class DotnetTrx(unittest.TestCase):
    def test_real_trx_outcomes_and_ids(self):
        base = read_real(self, "dotnet", "3-real-test", "base", BASE_DIR)
        by = {r["id"]: r for r in base}
        self.assertEqual(by["Shop.Tests.BulkTests.GivesTenItemsTenPercentOff"]["outcome"], "failed")
        self.assertIn("Assert.Equal() Failure", by["Shop.Tests.BulkTests.GivesTenItemsTenPercentOff"]["message"])
        self.assertEqual(by["Shop.Tests.BulkTests.LeavesASmallOrderAtFullPrice"]["outcome"], "passed")
        self.assertEqual(by["Shop.Tests.BulkTests.LeavesASmallOrderAtFullPrice"]["group"], "Shop.Tests.BulkTests")

    def test_exception_skip_and_byte_order_mark(self):
        # Written by hand in the shape of the real file above: an exception and a skipped test.
        with open(data_files("dotnet", "3-real-test", "base")[0], encoding="utf-8") as fh:
            text = fh.read().replace("<worktree>", BASE_DIR)
        text = text.replace("Assert.Equal() Failure: Values differ", "System.InvalidOperationException : the price list is empty", 1)
        text = text.replace('outcome="Passed"', 'outcome="NotExecuted"', 1)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "run.trx")
            with open(path, "w", encoding="utf-8-sig") as fh:
                fh.write(text)
            out = {r["id"]: r for r in cg.read_report("dotnet-trx", path)}
            folder = cg.read_report("dotnet-trx", d)
        failed = out["Shop.Tests.BulkTests.GivesTenItemsTenPercentOff"]
        self.assertEqual((failed["outcome"], failed["type"]), ("error", "System.InvalidOperationException"))
        self.assertEqual(out["Shop.Tests.BulkTests.LeavesASmallOrderAtFullPrice"]["outcome"], "skipped")
        self.assertEqual(len(folder), 2)

    def test_unreadable_trx_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.trx")
            with open(path, "w") as fh:
                fh.write("<TestRun><Results>")
            self.assertIsNone(cg.read_report("dotnet-trx", path))
            os.remove(path)
            self.assertIsNone(cg.read_report("dotnet-trx", d))


class NewPlaceholdersAndConfig(unittest.TestCase):
    def test_classes_csv_and_dotnet_filter(self):
        cmd = cg.expand_command("mvn -q test -Dtest={classes_csv}",
                                ["src/test/java/shop/BulkTest.java", "src/test/java/shop/FormatTest.java"])
        self.assertEqual(cmd, "mvn -q test -Dtest=shop.BulkTest,shop.FormatTest")
        cmd = cg.expand_command("dotnet test --filter {dotnet_filter}",
                                ["tests/Shop.Tests/BulkTests.cs", "tests/Shop.Tests/FormatTests.cs"])
        self.assertEqual(cmd, "dotnet test --filter 'FullyQualifiedName~BulkTests|FullyQualifiedName~FormatTests'")
        self.assertEqual(cg.expand_command("x {classes_csv} {dotnet_filter}", []), "x '' ''")

    def test_names_regex_for_swift_test_filter(self):
        cmd = cg.expand_command("swift test --parallel --filter {names_regex}",
                                ["Tests/ShopTests/BulkTests.swift", "Tests/ShopTests/FormatTests.swift"])
        self.assertEqual(cmd, "swift test --parallel --filter 'BulkTests|FormatTests'")
        self.assertEqual(cg.expand_command("x {names_regex}", ["Tests/A+B.swift"]), "x 'A\\+B'")
        c = cg.validate_config(dict(BASE_CFG, test_command="swift test --filter {names_regex}", report_format="junit-xml",
                                    report_path=".build/cg-xunit"))
        self.assertEqual(c["report_path"], ".build/cg-xunit")

    def test_swift_writes_xctest_and_swift_testing_reports_into_one_folder(self):
        # Real files: XCTest's results.xml and Swift Testing's results-swift-testing.xml, read as one folder.
        for eco, xctest, swift_testing in (("swift", 2, 0), ("swift-testing", 0, 2)):
            with self.subTest(eco=eco):
                recs = read_real(self, eco, "3-real-test", "base", BASE_DIR)
                self.assertEqual(len(recs), xctest + swift_testing)
                self.assertEqual(sorted(r["outcome"] for r in recs), ["failed", "passed"])

    def test_a_file_name_cannot_inject_through_the_new_placeholders(self):
        cmd = cg.expand_command("dotnet test --filter {dotnet_filter}", ["tests/x$(touch INJECTED).cs"])
        self.assertEqual(cmd, "dotnet test --filter 'FullyQualifiedName~x$(touch INJECTED)'")

    def test_the_new_placeholders_and_format_are_accepted(self):
        c = cg.validate_config(dict(BASE_CFG, test_command="mvn test -Dtest={classes_csv}", report_format="junit-xml",
                                    report_path="target/surefire-reports"))
        self.assertEqual(c["report_path"], "target/surefire-reports")
        c = cg.validate_config(dict(BASE_CFG, test_command="dotnet test --filter {dotnet_filter}",
                                    report_format="dotnet-trx", report_path="TestResults"))
        self.assertEqual(c["report_format"], "dotnet-trx")

    def test_every_fixture_configuration_loads(self):
        for eco in sorted(os.listdir(FIXTURES)):
            path = os.path.join(FIXTURES, eco, "base", "change-guard.json")
            if not os.path.exists(path):
                continue
            with self.subTest(eco=eco):
                with open(path, encoding="utf-8") as fh:
                    c = cg.validate_config(json.load(fh))
                self.assertIn(c["report_format"], cg.REPORT_FORMATS)
                self.assertEqual(c["report_format"], FORMATS[eco])


class RelativeIdsAndNotes(unittest.TestCase):
    def test_relative_records_strips_both_spellings_of_the_folder(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.realpath(d)
            recs = [cg._rec(d + "/tests/a.test.js::a", d + "/tests/a.test.js", "passed"),
                    cg._rec(real + "/tests/b.test.js::b", real + "/tests/b.test.js", "passed"),
                    cg._rec("shop.BulkTest.x", "shop.BulkTest", "passed")]
            out = cg.relative_records(recs, d)
        self.assertEqual([r["id"] for r in out], ["tests/a.test.js::a", "tests/b.test.js::b", "shop.BulkTest.x"])
        self.assertEqual(out[0]["group"], "tests/a.test.js")
        self.assertIsNone(cg.relative_records(None, "/x"))

    def test_class_named_groups_belong_to_their_file(self):
        self.assertTrue(cg._in_files({"group": "shop.BulkTest"}, ["src/test/java/shop/BulkTest.java"]))
        self.assertTrue(cg._in_files({"group": "Shop.Tests.BulkTests"}, ["tests/Shop.Tests/BulkTests.cs"]))
        self.assertFalse(cg._in_files({"group": "shop.FormatTest"}, ["src/test/java/shop/BulkTest.java"]))
        self.assertFalse(cg._in_files({"group": ""}, ["src/test/java/shop/BulkTest.java"]))


class UnprovenIsAWarning(unittest.TestCase):
    def test_ok_unproven_is_a_warning_annotation_on_github(self):
        r = Repo(self, config={"probe": "off"})
        new_fn = "def line_total(price, qty):\n    return price * qty\n\n\ndef bulk_total(price, qty):\n    return price * qty * 9 // 10\n"
        weak = test_module("from src.pricing import bulk_total", "bulk_total(1, 10)")
        code, res, out = r.change({"src/pricing.py": new_fn, "tests/test_bulk.py": weak}, env={"GITHUB_ACTIONS": "true"})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-unproven"), out)
        self.assertIn("::warning title=change-guard PASSED::", out)
        self.assertNotIn("::notice title=change-guard PASSED::", out)


if __name__ == "__main__":
    unittest.main()
