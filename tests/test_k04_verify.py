# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Tests for the findings of the first separate verification round, of version 0.2.1 (K04 in CHANGELOG.md). Demo project, no real data.

Run from the repository root:  python3 -m unittest discover -s tests -v
Standard library only. Each test fails on the 0.2.1 code as first written
and passes after the K04 changes.
"""

import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_v21_fixes import BASE_CFG, FIXED, PRICING, TEST_EXISTS, Repo, cg, test_module  # noqa: E402


class K04StubNeedsAStubBody(unittest.TestCase):
    def test_k04_decorator_alone_does_not_make_a_stub(self):
        src = textwrap.dedent('''\
            import abc
            @abc.abstractmethod
            def bulk_total(price, qty):
                return price * qty * 0.9
            def overload(f):
                return f
            @overload
            def other(x):
                return x + 1
            @abc.abstractmethod
            def real_stub(x):
                """Only a docstring and a raise."""
                raise NotImplementedError
            ''')
        funcs, _ = cg.python_definitions(src)
        stubs = sorted(q for q, nodes in funcs.items() if all(cg.is_stub(n) for n in nodes))
        self.assertEqual(stubs, ["real_stub"])

    def test_k04_module_level_abstractmethod_with_a_real_body_is_probed(self):
        head = "import abc\n" + PRICING + "\n\n@abc.abstractmethod\ndef bulk_total(price, qty):\n    return price * qty * 9 // 10\n"
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": head, "tests/test_exists.py": TEST_EXISTS})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "probe-passes", 1), out)


class K04ConfigThroughASymlink(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "symbolic links need extra rights on Windows")
    def test_k04_absolute_config_path_through_a_symlink_is_read_from_the_base(self):
        r = Repo(self)
        holder = tempfile.mkdtemp(prefix="cg-k04-")
        link = os.path.join(holder, "linked-repo")
        os.symlink(r.repo, link)
        # Version 0.3.1 (M10 of the 0.3.0 audit): remove the folder too, not only the link.
        self.addCleanup(shutil.rmtree, holder, True)
        loose = dict(BASE_CFG, exempt=["src/**"])
        r.git("checkout", "--quiet", "-B", "change", "main")
        r.commit({"src/pricing.py": "def line_total(price, qty):\n    return 0\n", "change-guard.json": json.dumps(loose)})
        # The repository is named through the link, the configuration by its real path.
        code, res, out = r.run(repo=link, args=("--config", os.path.join(os.path.realpath(r.repo), "change-guard.json")))
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "no-test", 1), out)
        self.assertIn("config: change-guard.json from the base commit", out)


class K04HeadFailureNamesPassEnv(unittest.TestCase):
    def test_k04_a_hidden_variable_is_explained_in_the_hint(self):
        test = test_module("import os\nfrom src.pricing import line_total",
                           "os.environ['DATABASE_URL']\nself.assertEqual(line_total(-1, 2), 0)")
        r = Repo(self)
        code, res, out = r.change({"src/pricing.py": FIXED, "tests/test_fixed.py": test}, env={"DATABASE_URL": "postgres://demo"})
        self.assertEqual((res["result"], res["cause"]), ("STOPPED", "test-fails-on-head"), out)
        self.assertIn("pass_env", out)
        r2 = Repo(self, config={"pass_env": ["DATABASE_URL"]})
        code, res, out = r2.change({"src/pricing.py": FIXED, "tests/test_fixed.py": test}, env={"DATABASE_URL": "postgres://demo"})
        self.assertEqual((res["result"], res["cause"]), ("PASSED", "ok"), out)


if __name__ == "__main__":
    unittest.main()
