# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Tests for the two defects found by the second separate verification round (K08 in CHANGELOG.md). Demo project, no real data.

Run from the repository root:  python3 -m unittest discover -s tests -v
Standard library only. Each test fails on 0.2.2 as delivered and passes after
the K08 fixes, except the one marked as a regression check, which holds on both.
"""

import os
import stat
import sys
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_v21_fixes import PRICING, Repo  # noqa: E402

BROKEN = "def line_total(price, qty):\n    return price + qty\n"


class K08ShebangLineEndings(unittest.TestCase):
    TOOL = "#!/usr/bin/env python3\nprint('tool ran')\n"

    def test_k08_a_python_script_with_a_shebang_converted_to_crlf_needs_a_test(self):
        # The syntax tree is equal, but the system now looks for "python3\r".
        r = Repo(self, base_files={"src/tool.py": self.TOOL})
        code, res, out = r.change({"src/tool.py": self.TOOL.replace("\n", "\r\n").encode()})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "no-test", 1), out)

    def test_k08_a_trailing_space_on_the_shebang_line_needs_a_test(self):
        r = Repo(self, base_files={"src/tool.py": self.TOOL})
        code, res, out = r.change({"src/tool.py": self.TOOL.replace("python3\n", "python3 \n", 1)})
        self.assertEqual((res["result"], res["cause"], code), ("STOPPED", "no-test", 1), out)

    def test_k08_regression_check_crlf_below_an_unchanged_shebang_stays_exempt(self):
        body = self.TOOL + "\n\ndef f():\n    return 1\n"
        r = Repo(self, base_files={"src/tool.py": body})
        head = body.split("\n", 1)[0] + "\n" + body.split("\n", 1)[1].replace("\n", "\r\n")
        code, res, out = r.change({"src/tool.py": head.encode(), "src/pricing.py": PRICING.replace("qty\n", "qty   \n")})
        self.assertEqual((res["result"], res["cause"], code), ("EXEMPT", "whitespace-only", 0), out)


class K08UnreadableGitConfig(unittest.TestCase):
    TEST = textwrap.dedent('''\
        import os, subprocess, unittest
        from src.pricing import line_total


        class T(unittest.TestCase):
            def test_line_total(self):
                common = subprocess.run(["git", "rev-parse", "--git-common-dir"], stdout=subprocess.PIPE).stdout.decode().strip()
                os.chmod(os.path.join(os.path.abspath(common), "config"), 0)
                line_total(2, 3)
        ''')

    def test_k08_a_git_configuration_made_unreadable_by_the_tests_is_put_back(self):
        r = Repo(self)
        config = os.path.join(r.repo, ".git", "config")
        mode = stat.S_IMODE(os.stat(config).st_mode)
        with open(config, "rb") as fh:
            before = fh.read()
        self.addCleanup(os.chmod, config, mode)
        code, res, out = r.change({"src/pricing.py": BROKEN, "tests/test_line.py": self.TEST})
        self.assertEqual((res["result"], res["cause"], code), ("ERROR", "tampered", 2), out)
        self.assertEqual(stat.S_IMODE(os.stat(config).st_mode), mode, out)
        with open(config, "rb") as fh:
            self.assertEqual(fh.read(), before)


if __name__ == "__main__":
    unittest.main()
