# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Unit and integration tests for the version 0.2.1 fixes R1 to R20 (see CHANGELOG.md). Demo project, no real data.

Run from the repository root:  python3 -m unittest discover -s tests -v
Standard library only. Each test names the defect of the review of version 0.2.0
it checks (R1 to R20); every one of them fails on the 0.2.0 code.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, KIT)

import change_guard as cg  # noqa: E402

GUARD = os.path.join(KIT, "change_guard.py")
ENV = dict(os.environ)
ENV.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_AUTHOR_NAME": "Demo Engineer", "GIT_AUTHOR_EMAIL": "demo@example.invalid",
            "GIT_COMMITTER_NAME": "Demo Engineer", "GIT_COMMITTER_EMAIL": "demo@example.invalid"})
for var in ("CHANGE_GUARD_MODE", "CHANGE_GUARD_SKIP_BY", "CHANGE_GUARD_SKIP_REASON", "GITHUB_ACTIONS",
            "GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY"):
    ENV.pop(var, None)

BASE_CFG = {"protected": ["src/**"], "tests": ["tests/**/test_*.py"],
            "test_command": "{python} {cg_tools}/cg_unittest_report.py {report} {files}",
            "report_format": "unittest-json"}
PRICING = "def line_total(price, qty):\n    return price * qty\n"
FIXED = "def line_total(price, qty):\n    return max(0, price * qty)\n"
NEW_FN = PRICING + "\n\ndef bulk_total(price, qty):\n    total = price * qty\n    return total * 90 // 100 if qty >= 10 else total\n"


def test_module(imports, body):
    return "import unittest\n%s\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n%s\n" % (
        imports, textwrap.indent(textwrap.dedent(body), "        "))


TEST_FIXED = test_module("from src.pricing import line_total", "self.assertEqual(line_total(-1, 2), 0)")
TEST_EXISTS = test_module("from src import pricing", "self.assertTrue(hasattr(pricing, 'bulk_total'))")


class Repo:
    """A throwaway repository: main holds the base, the branch change holds the change."""

    def __init__(self, test, config=None, base_files=None):
        self.root = tempfile.mkdtemp(prefix="cg-v21-")
        test.addCleanup(shutil.rmtree, self.root, True)
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        self.git("init", "--quiet", "-b", "main")
        cfg = dict(BASE_CFG)
        cfg.update(config or {})
        files = {"src/__init__.py": "", "src/pricing.py": PRICING, "tests/__init__.py": "",
                 "change-guard.json": json.dumps(cfg), ".gitignore": ".change-guard/\n__pycache__/\n"}
        files.update(base_files or {})
        self.commit(files)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo] + list(args), env=ENV, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()

    def commit(self, files):
        for path, text in files.items():
            full = os.path.join(self.repo, *path.split("/"))
            if text is None:
                os.remove(full)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            if isinstance(text, bytes):
                with open(full, "wb") as fh:
                    fh.write(text)
            else:
                with open(full, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", "change")

    def change(self, files, **kw):
        self.git("checkout", "--quiet", "-B", "change", "main")
        self.commit(files)
        return self.run(**kw)

    def run(self, args=(), env=None, mode="block", repo=None, head="change", log=None):
        result = os.path.join(self.root, "result.json")
        if os.path.exists(result):
            os.remove(result)
        e = dict(ENV)
        e.update(env or {})
        started = time.monotonic()
        proc = subprocess.run([sys.executable, GUARD, "--repo", repo or self.repo, "--base", "main", "--head", head,
                               "--mode", mode, "--log", log or os.path.join(self.root, "runs.log"),
                               "--result-json", result] + list(args),
                              env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.wall = time.monotonic() - started
        res = None
        if os.path.exists(result):
            with open(result, encoding="utf-8") as fh:
                res = json.load(fh)
        return proc.returncode, res, proc.stdout.decode("utf-8", "replace")


class R1ConfigAndScriptFromTheBase(unittest.TestCase):
    def test_r1_config_edited_by_the_change_is_not_used(self):
        r = Repo(self)
        cfg = dict(BASE_CFG, exempt=["src/**"])
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty):\n    return 0\n",
                                   "change-guard.json": json.dumps(cfg)})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "no-test", 1), out)
        self.assertIn("guard-changed", res["notes"], out)
        self.assertIn("config: change-guard.json from the base commit", out)

    def test_r1_the_change_that_installs_the_guard_uses_its_own_config_and_says_so(self):
        r = Repo(self)
        r.git("rm", "--quiet", "change-guard.json")
        r.git("commit", "--quiet", "-m", "no guard yet")
        code, res, out = r.change({"change-guard.json": json.dumps(BASE_CFG), "src/pricing.py": FIXED,
                                   "tests/test_fixed.py": TEST_FIXED})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertIn("config-from-head", res["notes"])
        self.assertIn("is not on the base commit", out)

    def test_r1_ci_files_run_the_guard_from_the_base(self):
        for name in ("github-actions.yml", "gitlab-ci.yml", "Jenkinsfile.change-guard", "azure-pipelines.change-guard.yml"):
            with self.subTest(name=name):
                with open(os.path.join(KIT, "ci", name), encoding="utf-8") as fh:
                    text = fh.read()
                self.assertIn("git show", text)
                self.assertIn("cg_unittest_report.py", text)
                self.assertNotIn("python3 tools/change-guard/change_guard.py", text)

    def test_r1_example_config_does_not_exempt_the_workflows(self):
        with open(os.path.join(KIT, "change-guard.example.json"), encoding="utf-8") as fh:
            self.assertNotIn(".github/**", json.load(fh)["exempt"])


class R2Whitespace(unittest.TestCase):
    BULK = "def line_total(price, qty):\n    total = price * qty\n    if qty >= 10:\n        total = total * 90 // 100\n    return total\n"

    def test_r2_indentation_that_changes_python_is_not_exempt(self):
        r = Repo(self, base_files={"src/pricing.py": self.BULK})
        code, res, out = r.change({"src/pricing.py": self.BULK.replace("\n    return total", "\n        return total")})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "no-test"), out)

    def test_r2_whitespace_inside_a_string_is_not_exempt(self):
        r = Repo(self, base_files={"src/pricing.py": "SEP = 'a b'\n"})
        code, res, out = r.change({"src/pricing.py": "SEP = 'ab'\n"})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "no-test"), out)

    def test_r2_leading_whitespace_in_other_files_is_not_exempt(self):
        r = Repo(self, base_files={"src/rules.yaml": "bulk:\n  percent: 10\nlimit: 99\n"})
        code, res, out = r.change({"src/rules.yaml": "bulk:\n  percent: 10\n  limit: 99\n"})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "no-test"), out)

    def test_r2_honest_whitespace_is_still_exempt(self):
        # Version 0.2.2 (V5): only Python files are exempt this way; the YAML file of
        # version 0.2.1's test is now in test_v22_hardening.py, where it needs a test.
        r = Repo(self, base_files={"src/pricing.py": self.BULK})
        code, res, out = r.change({"src/pricing.py": self.BULK.replace("qty):\n", "qty):   \n") + "\n\n"})
        self.assertEqual((res["result"], res["cause"]), ("EXEMPT", "whitespace-only"), out)


class R3GeneratedMarker(unittest.TestCase):
    def test_r3_a_marker_added_by_the_change_does_not_exempt_it(self):
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": "# DO NOT EDIT without asking\ndef line_total(price, qty):\n    return 0\n"})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "no-test"), out)

    def test_r3_a_new_file_with_a_marker_is_not_exempt(self):
        r = Repo(self)
        code, res, out = r.change({"src/new_pb.py": "# Code generated by protoc. DO NOT EDIT.\nX = 1\n"})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "no-test"), out)


class R5Rename(unittest.TestCase):
    def test_r5_rename_with_an_edit_compares_with_the_old_path(self):
        big = PRICING + "\n\ndef tax(amount):\n    return amount * 21 // 100\n\n\ndef rounding(amount):\n    return round(amount, -1)\n"
        r = Repo(self, base_files={"src/pricing.py": big})
        test = test_module("from src.billing import line_total", "self.assertEqual(line_total(-1, 2), 0)")
        code, res, out = r.change({"src/pricing.py": None, "src/billing.py": big.replace("return price * qty", "return max(0, price * qty)"),
                                   "tests/test_billing.py": test})
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok", 0), out)
        self.assertNotIn("probe:", out)

    def test_r5_diff_of_a_renamed_file_holds_only_its_edits(self):
        r = Repo(self, base_files={"src/a.py": "def one():\n    return 1\n\n\ndef two():\n    return 2\n"})
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/a.py": None, "src/b.py": "def one():\n    return 1\n\n\ndef two():\n    return 3\n"})
        with mock.patch.dict(os.environ, {k: v for k, v in ENV.items() if k.startswith("GIT_")}):
            d = cg.diff_by_file(r.repo, "main", "change", ["src/a.py", "src/b.py"])
        self.assertEqual(d["src/b.py"]["added"], ["    return 3"])


class R6LeftoverProcesses(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "process groups are POSIX")
    def test_r6_a_child_left_running_does_not_hold_the_guard(self):
        r = Repo(self, config={"time_budget_seconds": 20})
        test = ("import subprocess, unittest\nfrom src.pricing import line_total\n"
                "subprocess.Popen(['sleep', '30'])\n\n\nclass T(unittest.TestCase):\n"
                "    def test_it(self):\n        self.assertEqual(line_total(-1, 2), 0)\n")
        code, res, out = r.change({"src/pricing.py": FIXED, "tests/test_fixed.py": test})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertLess(r.wall, 10)

    @unittest.skipIf(os.name == "nt", "process groups are POSIX")
    def test_r6_a_child_in_its_own_session_does_not_overrun_the_budget(self):
        r = Repo(self, config={"time_budget_seconds": 5})
        test = ("import subprocess, unittest\nfrom src.pricing import line_total\n"
                "subprocess.Popen(['sleep', '30'], start_new_session=True)\n\n\nclass T(unittest.TestCase):\n"
                "    def test_it(self):\n        self.assertEqual(line_total(-1, 2), 0)\n")
        code, res, out = r.change({"src/pricing.py": FIXED, "tests/test_fixed.py": test})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertLess(r.wall, 10)


class R7HiddenDefinitions(unittest.TestCase):
    def test_r7_definitions_inside_compound_statements_and_lambdas(self):
        src = textwrap.dedent("""\
            if True:
                def a():
                    return 1
            try:
                import decimal
            except ImportError:
                def b():
                    return 0
            else:
                def b():
                    return 2
            with open(__file__) as _fh:
                def c():
                    return 3
            d = lambda x: x + 1
            class K:
                e = lambda self: 5
            """)
        funcs, names = cg.python_definitions(src)
        self.assertEqual(sorted(funcs), ["K.e", "a", "b", "c", "d"])
        self.assertEqual(len(funcs["b"]), 2)
        new = cg.neutralise_python(src, ["a", "b", "d", "K.e"])
        ns = {"__file__": __file__}
        exec(compile(new, "<t>", "exec"), ns)
        self.assertIsNone(ns["a"]())
        self.assertIsNone(ns["b"]())
        self.assertIsNone(ns["d"](1))
        self.assertIsNone(ns["K"]().e())
        self.assertEqual(ns["c"](), 3)

    def test_r7_existence_test_of_a_function_under_if_is_stopped(self):
        r = Repo(self)
        fn = PRICING + "\n\nif True:\n    def bulk_total(price, qty):\n        return price * qty * 90 // 100\n"
        code, res, out = r.change({"src/pricing.py": fn, "tests/test_bulk.py": TEST_EXISTS})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "probe-passes"), out)

    def test_r7_existence_test_of_a_lambda_is_stopped(self):
        r = Repo(self)
        fn = PRICING + "\n\nbulk_total = lambda price, qty: price * qty * 90 // 100\n"
        code, res, out = r.change({"src/pricing.py": fn, "tests/test_bulk.py": TEST_EXISTS})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "probe-passes"), out)


class R8NewParameter(unittest.TestCase):
    def test_r8_unused_new_parameter_with_a_call_only_test_is_stopped(self):
        r = Repo(self)
        test = test_module("from src.pricing import line_total", "line_total(100, 2, discount=10)")
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty, discount=0):\n    return price * qty\n",
                                   "tests/test_discount.py": test})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "probe-passes"), out)
        self.assertEqual(res["classes"], {"tests.test_discount.T.test_it": "errored-new-symbol"})

    def test_r8_honest_test_of_a_new_parameter_passes(self):
        r = Repo(self)
        test = test_module("from src.pricing import line_total", "self.assertEqual(line_total(100, 2, discount=10), 180)")
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty, discount=0):\n    return price * qty * (100 - discount) // 100\n",
                                   "tests/test_discount.py": test})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-new-code"), out)

    def test_r8_a_renamed_parameter_is_not_probed(self):
        r = Repo(self, base_files={"src/pricing.py": PRICING + "\n\ndef tax(amount):\n    return amount * 21 // 100\n"})
        code, res, out = r.change({"src/pricing.py": FIXED + "\n\ndef tax(net):\n    return net * 21 // 100\n",
                                   "tests/test_fixed.py": TEST_FIXED})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertNotIn("probe: tax", out)

    def test_r8_positional_form_names_the_function(self):
        c = cg.validate_config(dict(BASE_CFG))
        self.assertEqual(cg.missing_symbol_name("TypeError: line_total() takes 2 positional arguments but 3 were given",
                                                {"line_total"}, c["_missing_rx"]), "line_total")


class R9PhaseHidden(unittest.TestCase):
    def test_r9_a_test_that_reads_the_phase_variable_is_stopped(self):
        r = Repo(self)
        test = test_module("import os", "self.assertEqual(os.environ.get('CHANGE_GUARD_PHASE'), 'head')")
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty):\n    return 0\n", "tests/test_line.py": test})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "test-fails-on-head"), out)

    def test_r9_a_test_that_reads_its_folder_name_is_stopped(self):
        r = Repo(self)
        test = test_module("import os", "self.assertNotIn(os.sep + 'base', os.getcwd())")
        code, res, out = r.change({"src/pricing.py": "def line_total(price, qty):\n    return 0\n", "tests/test_line.py": test})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "test-passes-on-base"), out)

    def test_r9_report_names_are_neutral(self):
        cfg = cg.validate_config(dict(BASE_CFG))
        with tempfile.TemporaryDirectory() as d:
            state = {"tmp_parent": d}
            # Version 0.3.1 (finding D2 of the 0.3.0 audit): the name was run-1, run-2 ... in run
            # order, so the head run could be recognised; now every run gets a random name of one shape.
            names = [os.path.basename(cg.report_location(cfg, d, state, phase)) for phase in ("head", "base", "base")]
            for name in names:
                self.assertRegex(name, r"^report-[0-9a-f]{12}\.jsonl$")
                self.assertNotIn("base", name)
                self.assertNotIn("head", name)
            self.assertEqual(len(set(names)), 3)


class R10R13Rewrite(unittest.TestCase):
    def check(self, src, names, call, expected_rest=None):
        new = cg.neutralise_python(src, names)
        ns = {}
        exec(compile(new, "<t>", "exec"), ns)
        self.assertIsNone(call(ns), new)
        if expected_rest:
            for name, value in expected_rest.items():
                self.assertEqual(ns[name](), value, new)
        return new

    def test_r10_form_feed_does_not_shift_the_rewrite(self):
        src = "def a():\n    return 1\n\x0c\ndef b():\n    return 2\n\ndef c():\n    return 3\n"
        self.check(src, ["b"], lambda ns: ns["b"](), {"a": 1, "c": 3})

    def test_r13_one_line_function_with_a_non_ascii_name(self):
        self.check("def gr\u00f6\u00dfe(x): return x + 1\n", ["gr\u00f6\u00dfe"], lambda ns: ns["gr\u00f6\u00dfe"](1))

    def test_r13_one_line_function_with_a_non_ascii_default(self):
        self.check("def f(x='\u00e9'): return x\n", ["f"], lambda ns: ns["f"]())

    def test_r13_body_on_the_closing_line_of_the_signature(self):
        src = "def total(\n    price: int,\n    qty: int,\n) -> int: return price * qty\n"
        self.check(src, ["total"], lambda ns: ns["total"](1, 2))

    def test_r13_one_line_docstring_only_function(self):
        new = self.check('def f(): """Stub."""\n', ["f"], lambda ns: ns["f"]())
        self.assertIn('"""Stub."""', new)

    def test_r13_crlf_source(self):
        self.check("def a():\r\n    return 1\r\n\r\ndef b():\r\n    return 2\r\n", ["b"], lambda ns: ns["b"](), {"a": 1})

    def test_r13_one_line_honest_change_passes(self):
        r = Repo(self)
        head = PRICING + "\n\ndef label(cents, unit='\u20ac'): return '%d %s' % (cents, unit)\n"
        test = test_module("from src.pricing import label", "self.assertEqual(label(5), '5 \u20ac')")
        code, res, out = r.change({"src/pricing.py": head, "tests/test_label.py": test})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-new-code"), out)


class R11Stubs(unittest.TestCase):
    def test_r11_stub_bodies_are_recognised(self):
        src = textwrap.dedent('''\
            import abc, typing
            class S(abc.ABC):
                @abc.abstractmethod
                def area(self):
                    return 1
                @typing.overload
                def f(self, x: int) -> int: ...
                def g(self):
                    """Only a docstring."""
                def h(self):
                    pass
                def i(self):
                    raise NotImplementedError("later")
                def j(self):
                    return 2
            ''')
        funcs, _ = cg.python_definitions(src)
        stubs = sorted(q for q, nodes in funcs.items() if all(cg.is_stub(n) for n in nodes))
        # S.area has a real body: since K04 a decorator alone no longer makes a stub.
        self.assertEqual(stubs, ["S.f", "S.g", "S.h", "S.i"])

    def test_r11_abstract_method_with_its_implementation_passes(self):
        base = "import abc\n\n\nclass Shape(abc.ABC):\n    pass\n"
        head = ("import abc\n\n\nclass Shape(abc.ABC):\n    @abc.abstractmethod\n    def area(self):\n"
                "        raise NotImplementedError\n\n\nclass Square(Shape):\n    def __init__(self, side):\n"
                "        self.side = side\n\n    def area(self):\n        return self.side * self.side\n")
        test = test_module("from src.shapes import Square", "self.assertEqual(Square(3).area(), 9)")
        r = Repo(self, base_files={"src/shapes.py": base})
        code, res, out = r.change({"src/shapes.py": head, "tests/test_shapes.py": test})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-new-code"), out)
        self.assertNotIn("Shape.area", out)


class R12ImportTime(unittest.TestCase):
    def test_r12_function_used_at_import_time_counts_as_noticed(self):
        head = (PRICING + "\n\ndef load_rates():\n    return {'bulk': 10}\n\n\nRATES = load_rates()\nBULK = RATES['bulk']\n\n\n"
                "def bulk_total(price, qty):\n    return price * qty * (100 - BULK) // 100\n")
        test = test_module("from src.pricing import bulk_total", "self.assertEqual(bulk_total(100, 10), 900)")
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": head, "tests/test_bulk.py": test})
        self.assertEqual((res["result"], res["cause"], code), ("PASSED", "ok-new-code", 0), out)


class R14NeverWithoutAVerdict(unittest.TestCase):
    def test_r14_latin1_source_is_probed_in_its_encoding(self):
        r = Repo(self)
        src = (b"# -*- coding: latin-1 -*-\nLABEL = '\xe9t\xe9'\n\ndef line_total(price, qty):\n    return price * qty\n\n\n"
               b"def bulk(p, q):\n    return p * q * 9 // 10\n")
        test = test_module("from src.pricing import bulk", "self.assertEqual(bulk(10, 10), 90)")
        code, res, out = r.change({"src/pricing.py": src, "tests/test_b.py": test})
        self.assertIsNotNone(res, out)
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok-new-code"), out)
        self.assertTrue(os.path.exists(os.path.join(r.root, "runs.log")))

    def test_r14_unexpected_error_ends_as_error_with_a_log_line_and_exit_0_in_report_mode(self):
        r = Repo(self)
        r.change({"src/pricing.py": FIXED, "tests/test_fixed.py": TEST_FIXED})
        log = os.path.join(r.root, "inproc.log")
        result = os.path.join(r.root, "inproc.json")
        with mock.patch.dict(os.environ, ENV, clear=True), \
                mock.patch.object(cg, "evaluate", side_effect=RuntimeError("boom")), \
                mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            code = cg.main(["--repo", r.repo, "--base", "main", "--head", "change", "--mode", "report",
                            "--log", log, "--result-json", result])
        self.assertEqual(code, 0)
        with open(result, encoding="utf-8") as fh:
            res = json.load(fh)
        self.assertEqual((res["result"], res["cause"]), ("ERROR", "internal"))
        self.assertIn("RuntimeError (boom)", res["message"])
        with open(log, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 1)


class R15Environment(unittest.TestCase):
    def test_r15_command_environment_is_an_allowlist(self):
        cfg = cg.validate_config(dict(BASE_CFG, pass_env=["JAVA_*"]))
        fake = {"PATH": "/bin", "HOME": "/home/x", "GITHUB_ENV": "/tmp/e", "GITHUB_TOKEN": "t", "DEPLOY_TOKEN": "s",
                "AWS_SECRET_ACCESS_KEY": "k", "JAVA_HOME": "/jdk", "LC_ALL": "C"}
        with mock.patch.dict(os.environ, fake, clear=True):
            env = cg.command_environment(cfg, {"CHANGE_GUARD_REPORT": "/r"})
        self.assertEqual(sorted(env), ["CHANGE_GUARD_REPORT", "HOME", "JAVA_HOME", "LC_ALL", "PATH"])

    def test_r15_pass_env_cannot_name_a_ci_token(self):
        with self.assertRaises(cg.GuardStop):
            cg.validate_config(dict(BASE_CFG, pass_env=["GITHUB_TOKEN"]))

    def test_r15_tests_cannot_reach_secrets_or_ci_files_and_tampering_is_an_error(self):
        r = Repo(self)
        genv = os.path.join(r.root, "github_env")
        with open(genv, "w") as fh:
            fh.write("KEEP=1\n")
        log = os.path.join(r.repo, ".change-guard", "runs.log")
        seen = os.path.join(r.root, "seen.txt")
        test = ("import os, unittest\nfrom src.pricing import line_total\n"
                "open(%r, 'a').write(os.environ.get('DEPLOY_TOKEN', 'none') + ' ' + str('GITHUB_ENV' in os.environ) + '\\n')\n"
                "open(%r, 'a').write('NODE_OPTIONS=--require /tmp/evil.js\\n')\n"
                "os.makedirs(os.path.dirname(%r), exist_ok=True)\n"
                "open(%r, 'a').write('cg2\\tforged\\n')\n\n\n"
                "class T(unittest.TestCase):\n    def test_it(self):\n        self.assertEqual(line_total(-1, 2), 0)\n"
                % (seen, genv, log, log))
        code, res, out = r.change({"src/pricing.py": FIXED, "tests/test_fixed.py": test}, log=log,
                                  env={"GITHUB_ENV": genv, "DEPLOY_TOKEN": "s3cr3t"})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "tampered", 2), out)
        with open(seen) as fh:
            self.assertEqual(set(fh.read().split("\n")) - {""}, {"none False"})
        with open(genv) as fh:
            self.assertEqual(fh.read(), "KEEP=1\n")
        with open(log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("\tERROR\ttampered\t", lines[0])


class R16ReportPath(unittest.TestCase):
    def test_r16_report_path_must_stay_in_the_worktree(self):
        for bad in ("../../victim", "/tmp/victim", ".", "./", "a/../../b", "C:/x", "\\\\server\\share"):
            with self.subTest(path=bad):
                with self.assertRaises(cg.GuardStop):
                    cg.validate_config(dict(BASE_CFG, report_format="junit-xml", report_path=bad))
        cg.validate_config(dict(BASE_CFG, report_format="junit-xml", report_path="build/test-results/test"))


class R17Placeholders(unittest.TestCase):
    def test_r17_a_file_name_cannot_inject_through_a_later_placeholder(self):
        cmd = cg.expand_command("{python} -m unittest {files} {dirs}", ["tests/x$(touch INJECTED){dirs}/test_a.py"])
        self.assertIn("'tests/x$(touch INJECTED){dirs}/test_a.py'", cmd)
        self.assertIn("'./tests/x$(touch INJECTED){dirs}'", cmd)
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(cmd, shell=True, cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertFalse(os.path.exists(os.path.join(d, "INJECTED")))


class R18PathsInTheDiff(unittest.TestCase):
    def test_r18_spaces_and_non_ascii_names_keep_their_diff(self):
        r = Repo(self)
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/my pricing.py": "def a():\n    return 1\n", "src/prijs\u00e9.js": "export function bulkTotal() { return 1; }\n"})
        with mock.patch.dict(os.environ, {k: v for k, v in ENV.items() if k.startswith("GIT_")}):
            d = cg.diff_by_file(r.repo, "main", "change", ["src/my pricing.py", "src/prijs\u00e9.js"])
            names, _ = cg.added_symbols(r.repo, "main", "change", [("A", "src/prijs\u00e9.js")], d)
        self.assertEqual(sorted(d), ["src/my pricing.py", "src/prijs\u00e9.js"])
        self.assertIn("bulkTotal", names)


class R19Shallow(unittest.TestCase):
    def test_r19_shallow_clone_is_named(self):
        r = Repo(self)
        r.commit({"README.txt": "main moves on\n"})
        r.git("checkout", "--quiet", "-b", "change", "main~1")
        r.commit({"src/pricing.py": FIXED, "tests/test_fixed.py": TEST_FIXED})
        clone = os.path.join(r.root, "clone")
        subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--no-local", "-b", "change", "file://" + r.repo, clone],
                       env=ENV, check=True)
        subprocess.run(["git", "-C", clone, "fetch", "--quiet", "--depth", "1", "origin", "main:main"], env=ENV, check=True)
        code, res, out = r.run(repo=clone, head="HEAD")
        self.assertEqual((res["result"], res["cause"]), ("ERROR", "git"), out)
        self.assertIn("This clone is shallow", res["message"])


class R20RenamedTest(unittest.TestCase):
    def test_r20_a_renamed_test_file_is_not_reported_as_deleted(self):
        old = test_module("from src.pricing import line_total", "self.assertEqual(line_total(1, 2), 2)")
        r = Repo(self, base_files={"tests/test_old.py": old})
        code, res, out = r.change({"tests/test_old.py": None, "tests/test_renamed.py": old,
                                   "src/pricing.py": FIXED, "tests/test_fixed.py": TEST_FIXED})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)
        self.assertNotIn("test-deleted", res["notes"], out)


if __name__ == "__main__":
    unittest.main()
