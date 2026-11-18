#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Seeded cases for the change guard. Demo project, no real data.

Builds a throwaway git repository in a temporary folder with a tiny example
project (standard library unittest only, nothing to install), creates one
branch per seeded case, runs change_guard.py on each in blocking mode, checks
the result against the expected one, prints a table, and removes the folder.
Version 0.2.0 runs with per-test reports (report_format "unittest-json").

The five basic seeded cases:
  S1 a behaviour change with no test                      -> stopped
  S2 a change whose new test also passes without it       -> stopped
  S3 a good change                                        -> passes
  S4 an exempt change                                     -> passes untouched
  S5 the skip step used once                              -> passes and is logged

Extra checks of the guard's own edges (not part of the five):
  E1 a change whose new test fails on the head            -> stopped
  E2 a skip requested without a reason                    -> stopped
  E3 a test run longer than the time budget               -> time budget message
  E4 S1 again in report-only mode                         -> lets it through, says it would stop
  E5 a base commit whose package does not import          -> error, unrelated base failure
  E6 a new test that fails once on the head, then passes  -> passes, with a note

Library cases for version 0.2.0 (the guard's own self-test):
  S6  new function, its new test only calls it            -> stopped by the probe
  S6n the same with the probe off, policy "note"          -> passes, unproven, with the reason
  S6s the same with the probe off, policy "stop"          -> stopped
  S7  new function, its test mocks it                     -> stopped by the probe
  S8  new function, its test only checks it exists        -> stopped by the probe
  S8n the same with the probe off                         -> passes (the known limit)
  S9  new function with a real assertion                  -> passes, new code
  S10 a pure rename of a protected file                   -> exempt
  S11 a new test that depends on a clock                  -> stopped, flaky on the base
  S12 an existing test weakened next to an honest new one -> passes, with notes
  S12s the same with check_edited_tests "stop"            -> stopped
  S13 a whitespace-only change to protected code          -> exempt
  S14 the only new test is marked as an expected failure  -> stopped, nothing ran
  F1  S6 with no report (exit codes only)                 -> stopped by the probe
  F2  S9 with no report (exit codes only)                 -> passes

Library cases added in version 0.2.1, from the code review of version 0.2.0
(gaming routes it found, and honest changes 2.0 stopped by mistake):
  S15  indentation-only change that alters behaviour      -> stopped, no test
  S16  generated-code marker added by the change itself   -> stopped, no test
  S17  existence-only test, a text file beside the code   -> stopped by the probe
  S18  existence-only test, function defined under "if"   -> stopped by the probe
  S18t existence-only test, function defined under "try"  -> stopped by the probe
  S19  new unused parameter, test only calls it           -> stopped by the probe
  S20  test that reads the phase from the environment     -> stopped, fails on the head
  S20f test that reads the phase from its folder name     -> stopped, passes on the base
  H1   rename with an edit and a test of the edit         -> passes
  H2   new abstract method, tested through a subclass     -> passes, new code
  H3   new function used at import time                   -> passes, new code
  H4   new one-line function with non-ASCII text          -> passes, new code

Library cases added in version 0.2.2, from the separate verification round of
version 0.2.1 (routes that passed a gamed change, and a broken configuration;
the ids in brackets are the review items listed in CHANGELOG.md):
  S21  test plants a git hook in the repository's .git    -> error, tampered (V3a)
  S21c test points the repository's hooks to its own folder -> error, tampered (V3a)
  S22  test starts a process that patches the base folder -> error, tampered (V3b)
  S23  protected shell script converted to CRLF           -> stopped, no test (V5)
  S23b space added after a shell line continuation        -> stopped, no test (V5)
  S24  broken base configuration, repaired together with
       an untested code change                            -> error, configuration (V7)
  S25  test asserts only that git status is clean         -> stopped, passes on the base (V4)
  H5   broken base configuration, change only repairs it -> exempt, config-repair (V7)
  H6   broken base configuration, repair with a fix and
       the recorded skip step                             -> skipped, recorded (V7)

Then the normal-change series: ten normal changes in a row on one branch, none
of which should be stopped, and the cost and record figures (median added
time, one log line per run).

Usage: python3 seed_cases.py [--keep] [--normal-runs 10]
       python3 seed_cases.py --export DIR   (prepare a demonstration repository locally; nothing is pushed)
Needs only git and the Python 3 standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "change_guard.py")
REPORTER = os.path.join(HERE, "cg_unittest_report.py")

# Git runs with a neutral identity and without the machine's global config, so
# hooks, signing or aliases on this computer cannot change the result.
GIT_ENV = dict(os.environ)
GIT_ENV["PYTHONDONTWRITEBYTECODE"] = "1"
GIT_ENV.update({
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Demo Engineer",
    "GIT_AUTHOR_EMAIL": "demo@example.invalid",
    "GIT_COMMITTER_NAME": "Demo Engineer",
    "GIT_COMMITTER_EMAIL": "demo@example.invalid",
})
for var in ("CHANGE_GUARD_MODE", "CHANGE_GUARD_SKIP_BY", "CHANGE_GUARD_SKIP_REASON", "CHANGE_GUARD_REF", "GITHUB_ACTIONS"):
    GIT_ENV.pop(var, None)

CONFIG = {
    "_comment": "Demo project, no real data. Example configuration for the seeded cases.",
    "protected": ["src/**"],
    "exempt": ["docs/**", "*.md", "requirements*.txt"],
    "tests": ["tests/**/test_*.py"],
    "test_support": ["tests/**/helpers.py"],
    "test_command": "{python} {cg_tools}/cg_unittest_report.py {report} {files}",
    "report_format": "unittest-json",
    "time_budget_seconds": 300,
    "mode": "report",
    "log_file": ".change-guard/runs.log",
    "pass_env": ["DEMO_TICK_FILE"],
}

# Version 0.1.0 configuration: exit codes only, no per-test report (cases F1, F2).
CONFIG_NO_REPORT = dict(CONFIG, test_command="{python} -m unittest {files}", report_format="none")

PRICING_V1 = '''\
"""Order pricing for the demo shop. Demo project, no real data."""


def line_total(unit_price_cents, quantity):
    """Price of one order line in cents."""
    if quantity < 0:
        raise ValueError("quantity must not be negative")
    return unit_price_cents * quantity


def order_total(lines):
    """Sum of all lines, each given as (unit_price_cents, quantity)."""
    return sum(line_total(price, qty) for price, qty in lines)
'''

# The behaviour change used in several cases: 10 percent off from 10 items.
PRICING_BULK = PRICING_V1.replace(
    "    return unit_price_cents * quantity\n",
    "    total = unit_price_cents * quantity\n"
    "    if quantity >= 10:\n"
    "        total = total * 90 // 100\n"
    "    return total\n",
)

TEST_V1 = '''\
import unittest

from src.pricing import line_total, order_total


class PricingTest(unittest.TestCase):
    def test_line_total(self):
        self.assertEqual(line_total(250, 2), 500)

    def test_negative_quantity(self):
        with self.assertRaises(ValueError):
            line_total(250, -1)

    def test_order_total(self):
        self.assertEqual(order_total([(100, 1), (250, 2)]), 600)


if __name__ == "__main__":
    unittest.main()
'''

TEST_BULK_WEAK = '''\
import unittest

from src.pricing import line_total


class BulkDiscountTest(unittest.TestCase):
    def test_small_order_has_no_discount(self):
        # Passes with or without the discount: it never reaches 10 items.
        self.assertEqual(line_total(1000, 2), 2000)


if __name__ == "__main__":
    unittest.main()
'''

TEST_BULK_GOOD = '''\
import unittest

from src.pricing import line_total


class BulkDiscountTest(unittest.TestCase):
    def test_small_order_has_no_discount(self):
        self.assertEqual(line_total(1000, 2), 2000)

    def test_ten_items_get_ten_percent_off(self):
        self.assertEqual(line_total(1000, 10), 9000)


if __name__ == "__main__":
    unittest.main()
'''

TEST_BULK_WRONG = TEST_BULK_GOOD.replace("9000)", "8000)")

TEST_BULK_SLOW = TEST_BULK_GOOD.replace(
    "    def test_ten_items_get_ten_percent_off(self):\n",
    "    def test_ten_items_get_ten_percent_off(self):\n"
    "        import time\n"
    "        time.sleep(4)\n",
)

README_V1 = "# Demo shop\n\nDemo project, no real data.\n"

# Version 0.2.0 library cases: a new function, and five ways to test it.
PRICING_NEW_FN = PRICING_V1 + '''

def bulk_total(unit_price_cents, quantity):
    """Line total with 10 percent off from 10 items."""
    total = line_total(unit_price_cents, quantity)
    if quantity >= 10:
        total = total * 90 // 100
    return total
'''

TEST_NEW_FN_NO_ASSERT = '''\
import unittest

from src.pricing import bulk_total


class BulkTotalTest(unittest.TestCase):
    def test_bulk_total_runs(self):
        # Calls the new function and asserts nothing.
        bulk_total(1000, 10)


if __name__ == "__main__":
    unittest.main()
'''

TEST_NEW_FN_MOCK = '''\
import unittest
from unittest import mock

import src.pricing as pricing


class BulkTotalTest(unittest.TestCase):
    def test_bulk_total(self):
        # Replaces the function under test with a mock and checks the mock.
        with mock.patch.object(pricing, "bulk_total", return_value=9000):
            self.assertEqual(pricing.bulk_total(1000, 10), 9000)


if __name__ == "__main__":
    unittest.main()
'''

TEST_NEW_FN_EXISTS = '''\
import unittest

import src.pricing as pricing


class BulkTotalTest(unittest.TestCase):
    def test_bulk_total_exists(self):
        # Checks only that the name exists.
        self.assertTrue(hasattr(pricing, "bulk_total"))


if __name__ == "__main__":
    unittest.main()
'''

TEST_NEW_FN_HONEST = '''\
import unittest

from src.pricing import bulk_total


class BulkTotalTest(unittest.TestCase):
    def test_ten_items_get_ten_percent_off(self):
        self.assertEqual(bulk_total(1000, 10), 9000)

    def test_two_items_pay_full_price(self):
        self.assertEqual(bulk_total(1000, 2), 2000)


if __name__ == "__main__":
    unittest.main()
'''

# A counter that stands in for a clock, so the flaky cases give the same
# result on every machine: each test execution reads and bumps the number in
# the file named by DEMO_TICK_FILE.
TICK = '''\
import os


def tick():
    path = os.environ["DEMO_TICK_FILE"]
    with open(path) as fh:
        n = int(fh.read().strip() or 0) + 1
    with open(path, "w") as fh:
        fh.write(str(n))
    return n
'''

TEST_CLOCK = '''\
import unittest

from src.pricing import line_total
from tests.helpers import tick


class BulkClockTest(unittest.TestCase):
    def test_discount_applies_on_odd_seconds(self):
        # Depends on the clock, not on the change: passes on odd ticks only.
        self.assertEqual(tick() % 2, 1, "the simulated clock shows an even second")
        self.assertTrue(line_total(1000, 10) > 0)


if __name__ == "__main__":
    unittest.main()
'''

TEST_FLAKY_HEAD = '''\
import unittest

from src.pricing import line_total
from tests.helpers import tick


class BulkDiscountTest(unittest.TestCase):
    def test_ten_items_get_ten_percent_off(self):
        self.assertNotEqual(tick(), 1, "simulated cold start: the first run fails")
        self.assertEqual(line_total(1000, 10), 9000)


if __name__ == "__main__":
    unittest.main()
'''

TEST_XFAIL = '''\
import unittest

from src.pricing import line_total


class BulkDiscountTest(unittest.TestCase):
    @unittest.expectedFailure
    def test_ten_items_get_ten_percent_off(self):
        self.assertEqual(line_total(1000, 10), 8000)


if __name__ == "__main__":
    unittest.main()
'''

# S12: the base has an existing test of the old full price at ten items. The
# change gives the discount, brings an honest new test, and weakens the old
# test to a bare call instead of updating its expected value.
TEST_V1_WITH_TEN = TEST_V1.replace(
    "    def test_order_total(self):\n",
    "    def test_ten_items_full_price(self):\n"
    "        self.assertEqual(line_total(100, 10), 1000)\n\n"
    "    def test_order_total(self):\n",
)
TEST_V1_WEAKENED = TEST_V1_WITH_TEN.replace(
    "        self.assertEqual(line_total(100, 10), 1000)\n",
    "        line_total(100, 10)\n",
)

PRICING_WHITESPACE = PRICING_V1.replace("def order_total(lines):\n", "\ndef order_total(lines):  \n")

# Version 0.2.1 library cases.
# S15: "return total" moved into the if block, so orders under ten items return None.
PRICING_BULK_INDENTED = PRICING_BULK.replace(
    "        total = total * 90 // 100\n    return total\n",
    "        total = total * 90 // 100\n        return total\n")
# S16: a hand-written file that gets a generated-code marker in the same change.
PRICING_BULK_MARKED = "# DO NOT EDIT: generated by the pricing tool\n" + PRICING_BULK
# S18, S18t: the new function inside a compound statement.
PRICING_NEW_FN_IF = PRICING_V1 + '''

if True:
    def bulk_total(unit_price_cents, quantity):
        """Line total with 10 percent off from 10 items."""
        total = line_total(unit_price_cents, quantity)
        if quantity >= 10:
            total = total * 90 // 100
        return total
'''
PRICING_NEW_FN_TRY = PRICING_V1 + '''

try:
    from decimal import Decimal
except ImportError:
    Decimal = None
else:
    def bulk_total(unit_price_cents, quantity):
        """Line total with 10 percent off from 10 items."""
        total = line_total(unit_price_cents, quantity)
        if quantity >= 10:
            total = total * 90 // 100
        return total
'''
# S19: a new parameter that the code never uses, and a test that only passes it.
PRICING_NEW_PARAM = PRICING_V1.replace("def line_total(unit_price_cents, quantity):",
                                       "def line_total(unit_price_cents, quantity, discount_percent=0):")
TEST_NEW_PARAM_NO_ASSERT = '''\
import unittest

from src.pricing import line_total


class DiscountTest(unittest.TestCase):
    def test_discount_percent(self):
        # Passes the new argument and asserts nothing.
        line_total(1000, 10, discount_percent=10)


if __name__ == "__main__":
    unittest.main()
'''
# S20, S20f: tests that try to tell the head from the base instead of testing behaviour.
PRICING_BROKEN = PRICING_V1.replace("    return unit_price_cents * quantity\n", "    return 0\n")
TEST_READS_PHASE = '''\
import os
import unittest


class PhaseTest(unittest.TestCase):
    def test_line_total(self):
        # Asserts only on the phase the guard used to hand to the tests.
        self.assertEqual(os.environ.get("CHANGE_GUARD_PHASE"), "head")


if __name__ == "__main__":
    unittest.main()
'''
TEST_READS_FOLDER = '''\
import os
import unittest


class FolderTest(unittest.TestCase):
    def test_line_total(self):
        # Asserts only on the worktree folder name the guard used to choose.
        self.assertNotIn(os.sep + "base", os.getcwd())


if __name__ == "__main__":
    unittest.main()
'''
# H1: a module with two functions, renamed and edited; the test covers only the edit.
VAT_V1 = '''\
"""VAT helpers for the demo shop. Demo project, no real data."""


def vat_cents(net_cents):
    """VAT at 21 percent, rounded down."""
    return net_cents * 21 // 100


def round_cents(cents):
    """Round to whole cents."""
    return int(round(cents))
'''
VAT_V2 = VAT_V1.replace('"""VAT at 21 percent, rounded down."""\n    return net_cents * 21 // 100',
                        '"""VAT at 21 percent, rounded half up."""\n    return (net_cents * 21 + 50) // 100')
TEST_VAT = '''\
import unittest

from src.vat import vat_cents


class VatTest(unittest.TestCase):
    def test_vat_rounds_half_up(self):
        self.assertEqual(vat_cents(250), 53)


if __name__ == "__main__":
    unittest.main()
'''
# H2: an abstract method and its implementation, tested through the subclass.
SHAPES_V1 = '''\
"""Box shapes for the demo shop. Demo project, no real data."""
import abc


class Shape(abc.ABC):
    pass
'''
SHAPES_V2 = SHAPES_V1 + '''

class Square(Shape):
    def __init__(self, side):
        self.side = side

    def area(self):
        return self.side * self.side
'''
SHAPES_V2 = SHAPES_V2.replace("class Shape(abc.ABC):\n    pass\n",
                              "class Shape(abc.ABC):\n    @abc.abstractmethod\n    def area(self):\n"
                              "        \"\"\"Area in square centimetres.\"\"\"\n        raise NotImplementedError\n")
TEST_SHAPES = '''\
import unittest

from src.shapes import Square


class SquareTest(unittest.TestCase):
    def test_area(self):
        self.assertEqual(Square(3).area(), 9)


if __name__ == "__main__":
    unittest.main()
'''
# H3: a new function that the module calls at import time.
PRICING_IMPORT_TIME = PRICING_V1 + '''

def load_rates():
    """The discount rates, in percent."""
    return {"bulk": 10}


RATES = load_rates()
BULK_PERCENT = RATES["bulk"]


def bulk_total(unit_price_cents, quantity):
    """Line total with the bulk rate off from 10 items."""
    total = line_total(unit_price_cents, quantity)
    if quantity >= 10:
        total = total * (100 - BULK_PERCENT) // 100
    return total
'''
# H4: a new one-line function with non-ASCII text before its body.
PRICING_ONE_LINER = PRICING_V1 + '''

def price_label(cents, currency="\u20ac"): return "%d.%02d %s" % (cents // 100, cents % 100, currency)
'''
TEST_ONE_LINER = '''\
import unittest

from src.pricing import price_label


class LabelTest(unittest.TestCase):
    def test_label(self):
        self.assertEqual(price_label(1250), "12.50 \u20ac")


if __name__ == "__main__":
    unittest.main()
'''


# Version 0.2.2 library cases (V3a, V3b, V4, V5, V7 of the verification of 0.2.1).
# S21: the head-run test plants a post-checkout hook that poisons every later
# checkout without the broken code, so the base would fail "by assertion".
HOOK_POISON = ("#!/bin/sh\n"
               "grep -q 'return 0' src/pricing.py 2>/dev/null || "
               "printf 'import unittest\\nunittest.TestCase.setUp = lambda self: self.fail()\\n' >> src/__init__.py\n")
TEST_PLANTS_HOOK = '''\
import os
import subprocess
import unittest

from src.pricing import line_total

HOOK = %r


class LineTotalTest(unittest.TestCase):
    def test_line_total(self):
        # Asserts nothing; plants a hook in the main repository instead.
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], stdout=subprocess.PIPE).stdout.decode().strip()
        hook = os.path.join(os.path.abspath(common), "hooks", "post-checkout")
        if not os.path.exists(hook):
            with open(hook, "w") as fh:
                fh.write(HOOK)
            os.chmod(hook, 0o755)
        line_total(250, 2)


if __name__ == "__main__":
    unittest.main()
''' % HOOK_POISON
TEST_CHANGES_GIT_CONFIG = '''\
import os
import subprocess
import unittest

from src.pricing import line_total

HOOK = %r


class LineTotalTest(unittest.TestCase):
    def test_line_total(self):
        # Asserts nothing; points the repository's hooks to a folder of its own instead.
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hooks = os.path.join(os.path.dirname(here), "own-hooks")
        if not os.path.exists(hooks):
            os.makedirs(hooks)
            with open(os.path.join(hooks, "post-checkout"), "w") as fh:
                fh.write(HOOK)
            os.chmod(os.path.join(hooks, "post-checkout"), 0o755)
            common = subprocess.run(["git", "rev-parse", "--git-common-dir"], stdout=subprocess.PIPE).stdout.decode().strip()
            with open(os.path.join(os.path.abspath(common), "config"), "a") as fh:
                fh.write("[core]\\n\\thooksPath = %%s\\n" %% hooks)
        line_total(250, 2)


if __name__ == "__main__":
    unittest.main()
''' % HOOK_POISON
# S22: a process in its own session that patches the other worktrees of the run.
PATCHER = '''\
import glob, os, sys, time
mine, flag = sys.argv[1], sys.argv[2]
parent = os.path.dirname(mine)
end = time.time() + 15
done = False
while time.time() < end and not done:
    for d in glob.glob(os.path.join(parent, "wt-*")):
        init = os.path.join(d, "src", "__init__.py")
        if d != mine and os.path.exists(init):
            try:
                with open(init, "a") as fh:
                    fh.write("import unittest\\nunittest.TestCase.setUp = lambda self: self.fail()\\n")
                open(flag, "a").close()
                done = True
            except OSError:
                pass
    time.sleep(0.005)
'''
TEST_STARTS_PATCHER = '''\
import os
import subprocess
import sys
import time
import unittest

from src.pricing import line_total


class LineTotalTest(unittest.TestCase):
    def test_line_total(self):
        # Asserts nothing; starts a process that patches the later worktrees.
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        parent = os.path.dirname(here)
        flag, started = os.path.join(parent, "patched"), os.path.join(parent, "patcher-started")
        if not os.path.exists(started):
            open(started, "w").close()
            subprocess.Popen([sys.executable, os.path.join(here, "tests", "patcher.txt"), here, flag],
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.time() + 3
            while time.time() < deadline and not os.path.exists(flag):
                time.sleep(0.01)
        line_total(250, 2)


if __name__ == "__main__":
    unittest.main()
'''
# S23 and S23b: whitespace that changes what a shell script does.
DEPLOY_SH = "#!/bin/bash\nset -e\necho deploying\nexit 0\n"
RUN_SH = "#!/bin/sh\necho start \\\n  --safe-mode\n"
RUN_SH_SPACE = "#!/bin/sh\necho start \\ \n  --safe-mode\n"
# S24, H5, H6: the configuration on the target branch does not load.
BROKEN_CONFIG = '{ "protected": ["src/**"], \n'
# S25: a test whose only assertion is that its worktree looks clean to git.
TEST_GIT_STATUS_CLEAN = '''\
import os
import subprocess
import unittest

from src.pricing import line_total


class LineTotalTest(unittest.TestCase):
    def test_line_total(self):
        # Asserts only that git sees no change in the worktree.
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=here, stdout=subprocess.PIPE).stdout.strip()
        line_total(250, 2)
        self.assertEqual(dirty, b"")


if __name__ == "__main__":
    unittest.main()
'''


def git(repo, *args):
    proc = subprocess.run(["git", "-C", repo] + list(args), env=GIT_ENV,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), proc.stderr.decode()))
    return proc.stdout.decode().strip()


def write(repo, path, text):
    full = os.path.join(repo, *path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


def commit(repo, message, files):
    for path, text in files.items():
        if text is None:
            git(repo, "rm", "--quiet", path)
            continue
        write(repo, path, text)
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def branch_from_main(repo, name):
    git(repo, "checkout", "--quiet", "-B", name, "main")


def build_repo(root):
    repo = os.path.join(root, "demo-shop")
    os.makedirs(repo)
    git(repo, "init", "--quiet", "-b", "main")
    commit(repo, "Demo shop: first version", {
        "src/__init__.py": "",
        "src/pricing.py": PRICING_V1,
        "tests/test_pricing.py": TEST_V1,
        "docs/README.md": README_V1,
        "scripts/release_notes.py": "print('release notes')\n",
        "change-guard.json": json.dumps(CONFIG, indent=2) + "\n",
        ".gitignore": ".change-guard/\n__pycache__/\n",
        "tests/__init__.py": "",
        "tests/helpers.py": TICK,
    })
    return repo


DEMO_README = """\
# Change guard demo

**Demo project, no real data.** A tiny example shop with one check in its
pipeline: a change to `src/` must bring a new or changed test, and that test must
fail on the base commit and pass on the change. Only the changed test files run.

The three open pull requests are seeded cases:

1. A behaviour change with no test: stopped.
2. A behaviour change whose new test also passes without the change: stopped.
3. A behaviour change with a test that checks it: passes.

The check is `tools/change-guard/change_guard.py` (git and the Python standard
library only), wired in `.github/workflows/change-guard.yml`. Documentation-only
changes pass untouched, and a skip needs the label `change-guard-skip` plus a line
`Change-Guard-Skip-Reason: ...` in the description; both are recorded in the log.

The guard reduces a failure; it cannot rule it out, and it does not prove that a
change is correct.
"""

DEMO_BRANCHES = [
    ("demo/1-no-test", "Bulk discount, no test", {"src/pricing.py": PRICING_BULK}),
    ("demo/2-test-passes-without-the-change", "Bulk discount with a test that also passes without it",
     {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_WEAK}),
    ("demo/3-good-change", "Bulk discount with a test that checks it",
     {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_GOOD}),
]


def export_demo(target):
    """Prepare the demonstration repository in TARGET. Nothing is pushed."""
    target = os.path.abspath(target)
    if os.path.exists(target):
        print("The folder %s already exists; choose a new one." % target)
        return 1
    os.makedirs(target)
    git(target, "init", "--quiet", "-b", "main")
    with open(GUARD, encoding="utf-8") as fh:
        guard_src = fh.read()
    with open(REPORTER, encoding="utf-8") as fh:
        reporter_src = fh.read()
    with open(os.path.join(HERE, "ci", "github-actions.yml"), encoding="utf-8") as fh:
        workflow = fh.read()
    commit(target, "Demo shop with the change guard", {
        "README.md": DEMO_README,
        "src/__init__.py": "",
        "src/pricing.py": PRICING_V1,
        "tests/test_pricing.py": TEST_V1,
        "docs/README.md": README_V1,
        "scripts/release_notes.py": "print('release notes')\n",
        # The demo needs no pass_env: DEMO_TICK_FILE serves only the flaky cases of this script.
        "change-guard.json": json.dumps({k: v for k, v in CONFIG.items() if k != "pass_env"}, indent=2) + "\n",
        ".gitignore": ".change-guard/\n__pycache__/\n",
        "tools/change-guard/change_guard.py": guard_src,
        "tools/change-guard/cg_unittest_report.py": reporter_src,
        "tests/__init__.py": "",
        ".github/workflows/change-guard.yml": workflow,
    })
    for branch, title, files in DEMO_BRANCHES:
        branch_from_main(target, branch)
        commit(target, title, files)
    git(target, "checkout", "--quiet", "main")
    # Check every demo branch locally before anything is pushed.
    log_dir = tempfile.mkdtemp(prefix="change-guard-export-")
    try:
        log_path = os.path.join(log_dir, "runs.log")
        print("Prepared %s (nothing pushed). Local check of each demo branch:" % target)
        ok = True
        for (branch, title, _), expect in zip(DEMO_BRANCHES, ("STOPPED", "STOPPED", "PASSED")):
            code, out, res, wall = run_guard(target, "main", branch, log_path, mode="block", ref=branch)
            ok = ok and res["result"] == expect
            print("  %-40s %-8s %s" % (branch, res["result"], res["message"]))
    finally:
        shutil.rmtree(log_dir, ignore_errors=True)
    print("Branches: main, " + ", ".join(b for b, _, _ in DEMO_BRANCHES))
    return 0 if ok else 1


def run_guard(repo, base, head, log_path, mode="block", extra=None, ref="", env=None):
    result_path = os.path.join(os.path.dirname(log_path), "result.json")
    cmd = [sys.executable, GUARD, "--repo", repo, "--base", base, "--head", head,
           "--mode", mode, "--log", log_path, "--result-json", result_path, "--explain"]
    if ref:
        cmd += ["--ref", ref]
    cmd += extra or []
    run_env = dict(GIT_ENV)
    run_env.update(env or {})
    started = time.monotonic()
    proc = subprocess.run(cmd, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    wall = time.monotonic() - started
    with open(result_path, encoding="utf-8") as fh:
        result = json.load(fh)
    os.remove(result_path)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), result, wall


def indent(text, prefix="    | "):
    return "\n".join(prefix + line for line in text.rstrip().splitlines())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder for inspection")
    ap.add_argument("--normal-runs", type=int, default=10, help="length of the normal-change series (default 10)")
    ap.add_argument("--export", metavar="DIR", help="prepare the demonstration repository in DIR instead (nothing is pushed)")
    args = ap.parse_args()
    if args.export:
        return export_demo(args.export)

    root = tempfile.mkdtemp(prefix="change-guard-seed-")
    log_path = os.path.join(root, "runs.log")
    rows = []
    print("Seeded cases for the change guard. Demo project, no real data.")
    print("python %s, git %s, %s" % (platform.python_version(),
                                     subprocess.run(["git", "--version"], stdout=subprocess.PIPE).stdout.decode().split()[-1],
                                     platform.platform(terse=True)))
    try:
        repo = build_repo(root)

        def config_file(name, **changes):
            path = os.path.join(root, "config-%s.json" % name)
            base_cfg = changes.pop("_base", CONFIG)
            data = dict(base_cfg)
            data.update(changes)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            return path

        def tick_file(cid):
            path = os.path.join(root, "tick-%s.txt" % cid.lower())
            with open(path, "w") as fh:
                fh.write("0")
            return {"DEMO_TICK_FILE": path}

        def case(cid, title, expect_result, expect_exit, files, mode="block", extra=None,
                 expect_cause=None, base="main", config=None, env=None, base_files=None, expect_notes=()):
            if base_files:
                branch_from_main(repo, "base-" + cid.lower())
                commit(repo, "Base for " + cid, base_files)
                base = "base-" + cid.lower()
                git(repo, "checkout", "--quiet", "-B", "case-" + cid.lower(), base)
            else:
                branch_from_main(repo, "case-" + cid.lower())
            head = commit(repo, title, files) if files else git(repo, "rev-parse", "HEAD")
            more = list(extra or [])
            if config:
                more += ["--config", config]
            code, out, res, wall = run_guard(repo, base, head, log_path, mode=mode, extra=more, ref="seed-" + cid, env=env)
            ok = (res["result"] == expect_result and code == expect_exit
                  and (expect_cause is None or res["cause"] == expect_cause)
                  and all(n in res.get("notes", []) for n in expect_notes))
            rows.append({"id": cid, "title": title, "expected": expect_result, "got": res["result"],
                         "cause": res["cause"], "expected_cause": expect_cause or "", "exit": code,
                         "expected_exit": expect_exit, "ok": ok, "seconds": res["seconds"],
                         "message": res["message"], "mode": mode, "notes": res.get("notes", [])})
            print("\n[%s] %s" % (cid, title))
            print("    expected %s%s with exit %d, got %s (%s) with exit %d: %s" % (
                expect_result, " (%s)" % expect_cause if expect_cause else "", expect_exit,
                res["result"], res["cause"], code, "OK" if ok else "MISMATCH"))
            print(indent(out))

        # The five basic seeded cases.
        case("S1", "Bulk discount, no test", "STOPPED", 1,
             {"src/pricing.py": PRICING_BULK}, expect_cause="no-test")
        case("S2", "Bulk discount with a test that also passes without it", "STOPPED", 1,
             {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_WEAK}, expect_cause="test-passes-on-base")
        case("S3", "Bulk discount with a test that checks it", "PASSED", 0,
             {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_GOOD}, expect_cause="ok")
        case("S4", "Documentation only", "EXEMPT", 0,
             {"docs/README.md": README_V1 + "\nOrders of 10 items or more get 10 percent off.\n"}, expect_cause="exempt-only")
        case("S5", "Bulk discount, no test, skipped once with a reason", "SKIPPED", 0,
             {"src/pricing.py": PRICING_BULK},
             extra=["--skip-by", "demo-engineer",
                    "--skip-reason", "Urgent fix for the checkout total; the test follows in the next pull request"],
             expect_cause="skip")
        # Extra checks of the guard's own edges.
        case("E1", "Bulk discount with a test that fails on the head", "STOPPED", 1,
             {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_WRONG}, expect_cause="test-fails-on-head")
        case("E2", "Skip requested without a reason", "STOPPED", 1,
             {"src/pricing.py": PRICING_BULK},
             extra=["--skip-by", "demo-engineer", "--skip-reason", ""], expect_cause="skip-no-reason")
        case("E3", "A test run longer than a 3-second time budget", "TIMEOUT", 1,
             {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_SLOW},
             extra=["--time-budget", "3"], expect_cause="time-budget")
        case("E4", "S1 again in report-only mode", "STOPPED", 0,
             {"src/pricing.py": PRICING_BULK}, mode="report", expect_cause="no-test")
        case("E5", "A base commit whose package does not import", "ERROR", 2,
             {"src/__init__.py": "", "src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_GOOD},
             base_files={"src/__init__.py": "VERSION = (\n"}, expect_cause="base-error-unrelated")
        case("E6", "A new test that fails once on the head, then passes", "PASSED", 0,
             {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_FLAKY_HEAD},
             env=tick_file("E6"), expect_cause="ok", expect_notes=("flaky-on-head",))

        # Library cases of version 0.2.0.
        probe_off_note = config_file("probe-off-note", probe="off", base_error_policy="note")
        probe_off_stop = config_file("probe-off-stop", probe="off", base_error_policy="stop")
        edited_stop = config_file("edited-stop", check_edited_tests="stop")
        no_report = config_file("no-report", _base=CONFIG_NO_REPORT)
        case("S6", "New function whose new test only calls it", "STOPPED", 1,
             {"src/pricing.py": PRICING_NEW_FN, "tests/test_bulk_total.py": TEST_NEW_FN_NO_ASSERT}, expect_cause="probe-passes")
        case("S6n", "S6 with the probe off and the policy note", "PASSED", 0,
             {"src/pricing.py": PRICING_NEW_FN, "tests/test_bulk_total.py": TEST_NEW_FN_NO_ASSERT},
             config=probe_off_note, expect_cause="ok-unproven")
        case("S6s", "S6 with the probe off and the policy stop", "STOPPED", 1,
             {"src/pricing.py": PRICING_NEW_FN, "tests/test_bulk_total.py": TEST_NEW_FN_NO_ASSERT},
             config=probe_off_stop, expect_cause="base-error-only")
        case("S7", "New function whose test mocks it", "STOPPED", 1,
             {"src/pricing.py": PRICING_NEW_FN, "tests/test_bulk_total.py": TEST_NEW_FN_MOCK},
             expect_cause="probe-passes", expect_notes=("mocks-new-code",))
        case("S8", "New function whose test only checks that it exists", "STOPPED", 1,
             {"src/pricing.py": PRICING_NEW_FN, "tests/test_bulk_total.py": TEST_NEW_FN_EXISTS}, expect_cause="probe-passes")
        case("S8n", "S8 with the probe off (the known limit)", "PASSED", 0,
             {"src/pricing.py": PRICING_NEW_FN, "tests/test_bulk_total.py": TEST_NEW_FN_EXISTS},
             config=probe_off_note, expect_cause="ok")
        case("S9", "New function with a test that asserts its behaviour", "PASSED", 0,
             {"src/pricing.py": PRICING_NEW_FN, "tests/test_bulk_total.py": TEST_NEW_FN_HONEST}, expect_cause="ok-new-code")
        case("S10", "Pure rename of the pricing module", "EXEMPT", 0,
             {"src/pricing.py": None, "src/order_pricing.py": PRICING_V1,
              "tests/test_pricing.py": TEST_V1.replace("from src.pricing", "from src.order_pricing")},
             expect_cause="pure-rename")
        case("S11", "New test that depends on a clock", "STOPPED", 1,
             {"src/pricing.py": PRICING_BULK, "tests/test_bulk_clock.py": TEST_CLOCK},
             env=tick_file("S11"), expect_cause="flaky-on-base")
        case("S12", "Existing test weakened next to an honest new test", "PASSED", 0,
             {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_GOOD, "tests/test_pricing.py": TEST_V1_WEAKENED},
             base_files={"tests/test_pricing.py": TEST_V1_WITH_TEN}, expect_cause="ok", expect_notes=("assertions-removed",))
        case("S12s", "S12 with check_edited_tests set to stop", "STOPPED", 1,
             {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_GOOD, "tests/test_pricing.py": TEST_V1_WEAKENED},
             base_files={"tests/test_pricing.py": TEST_V1_WITH_TEN}, config=edited_stop,
             expect_cause="edited-test-would-fail", expect_notes=("assertions-removed", "edited-test-would-fail"))
        case("S13", "Whitespace-only change to protected code", "EXEMPT", 0,
             {"src/pricing.py": PRICING_WHITESPACE}, expect_cause="whitespace-only")
        case("S14", "The only new test is marked as an expected failure", "STOPPED", 1,
             {"src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_XFAIL},
             expect_cause="no-test-ran", expect_notes=("skip-marker-added",))
        case("F1", "S6 with no report (exit codes only)", "STOPPED", 1,
             {"src/pricing.py": PRICING_NEW_FN, "tests/test_bulk_total.py": TEST_NEW_FN_NO_ASSERT},
             config=no_report, expect_cause="probe-passes")
        case("F2", "S9 with no report (exit codes only)", "PASSED", 0,
             {"src/pricing.py": PRICING_NEW_FN, "tests/test_bulk_total.py": TEST_NEW_FN_HONEST},
             config=no_report, expect_cause="ok")

        # Library cases of version 0.2.1: gaming routes the review of 0.2.0 found.
        case("S15", "Indentation-only change that alters behaviour", "STOPPED", 1,
             {"src/pricing.py": PRICING_BULK_INDENTED}, base_files={"src/pricing.py": PRICING_BULK},
             expect_cause="no-test")
        case("S16", "Generated-code marker added by the change itself", "STOPPED", 1,
             {"src/pricing.py": PRICING_BULK_MARKED}, expect_cause="no-test")
        case("S17", "Existence-only test with a text file beside the code", "STOPPED", 1,
             {"src/pricing.py": PRICING_NEW_FN, "src/NOTES.txt": "Bulk pricing from ten items.\n",
              "tests/test_bulk_total.py": TEST_NEW_FN_EXISTS},
             expect_cause="probe-passes", expect_notes=("probe-partial",))
        case("S18", "Existence-only test, new function defined under if", "STOPPED", 1,
             {"src/pricing.py": PRICING_NEW_FN_IF, "tests/test_bulk_total.py": TEST_NEW_FN_EXISTS}, expect_cause="probe-passes")
        case("S18t", "Existence-only test, new function defined under try", "STOPPED", 1,
             {"src/pricing.py": PRICING_NEW_FN_TRY, "tests/test_bulk_total.py": TEST_NEW_FN_EXISTS}, expect_cause="probe-passes")
        case("S19", "New unused parameter, its test only passes it", "STOPPED", 1,
             {"src/pricing.py": PRICING_NEW_PARAM, "tests/test_discount.py": TEST_NEW_PARAM_NO_ASSERT}, expect_cause="probe-passes")
        case("S20", "Test that reads the phase from the environment", "STOPPED", 1,
             {"src/pricing.py": PRICING_BROKEN, "tests/test_phase.py": TEST_READS_PHASE}, expect_cause="test-fails-on-head")
        case("S20f", "Test that reads the phase from its folder name", "STOPPED", 1,
             {"src/pricing.py": PRICING_BROKEN, "tests/test_folder.py": TEST_READS_FOLDER}, expect_cause="test-passes-on-base")
        # Honest changes that version 0.2.0 stopped or reported as an error.
        case("H1", "Rename with an edit and a test of the edit", "PASSED", 0,
             {"src/tax.py": None, "src/vat.py": VAT_V2, "tests/test_vat.py": TEST_VAT},
             base_files={"src/tax.py": VAT_V1}, expect_cause="ok")
        case("H2", "New abstract method, tested through a subclass", "PASSED", 0,
             {"src/shapes.py": SHAPES_V2, "tests/test_shapes.py": TEST_SHAPES},
             base_files={"src/shapes.py": SHAPES_V1}, expect_cause="ok-new-code")
        case("H3", "New function used at import time", "PASSED", 0,
             {"src/pricing.py": PRICING_IMPORT_TIME, "tests/test_bulk_total.py": TEST_NEW_FN_HONEST}, expect_cause="ok-new-code")
        case("H4", "New one-line function with non-ASCII text", "PASSED", 0,
             {"src/pricing.py": PRICING_ONE_LINER, "tests/test_label.py": TEST_ONE_LINER}, expect_cause="ok-new-code")

        # Library cases of version 0.2.2: routes the verification of 0.2.1 found.
        case("S21", "Test plants a git hook in the repository's .git", "ERROR", 2,
             {"src/pricing.py": PRICING_BROKEN, "tests/test_hook.py": TEST_PLANTS_HOOK}, expect_cause="tampered")
        case("S21c", "Test points the repository's hooks to its own folder", "ERROR", 2,
             {"src/pricing.py": PRICING_BROKEN, "tests/test_gitconfig.py": TEST_CHANGES_GIT_CONFIG}, expect_cause="tampered")
        case("S22", "Test starts a process that patches the base worktree", "ERROR", 2,
             {"src/pricing.py": PRICING_BROKEN, "tests/test_patcher.py": TEST_STARTS_PATCHER, "tests/patcher.txt": PATCHER},
             expect_cause="tampered")
        case("S23", "Protected shell script converted to CRLF", "STOPPED", 1,
             {"src/deploy.sh": DEPLOY_SH.replace("\n", "\r\n")}, base_files={"src/deploy.sh": DEPLOY_SH},
             expect_cause="no-test")
        case("S23b", "Space added after a shell line continuation", "STOPPED", 1,
             {"src/run.sh": RUN_SH_SPACE}, base_files={"src/run.sh": RUN_SH}, expect_cause="no-test")
        repaired = json.dumps(CONFIG, indent=2) + "\n"
        case("S24", "Broken base configuration, repaired with untested code", "ERROR", 2,
             {"change-guard.json": repaired, "src/pricing.py": PRICING_BULK},
             base_files={"change-guard.json": BROKEN_CONFIG}, expect_cause="config")
        case("S25", "Test asserts only that git status is clean", "STOPPED", 1,
             {"src/pricing.py": PRICING_BROKEN, "tests/test_status.py": TEST_GIT_STATUS_CLEAN},
             expect_cause="test-passes-on-base")
        # Honest changes that version 0.2.1 could not let through.
        case("H5", "Broken base configuration, change only repairs it", "EXEMPT", 0,
             {"change-guard.json": repaired}, base_files={"change-guard.json": BROKEN_CONFIG},
             expect_cause="config-repair", expect_notes=("config-repair",))
        case("H6", "Broken base configuration, repair and fix, skipped", "SKIPPED", 0,
             {"change-guard.json": repaired, "src/pricing.py": PRICING_BULK, "tests/test_bulk.py": TEST_BULK_GOOD},
             base_files={"change-guard.json": BROKEN_CONFIG},
             extra=["--skip-by", "demo-engineer", "--skip-reason", "Repairs the guard configuration on main"],
             expect_cause="skip", expect_notes=("config-broken",))

        # Ten normal changes in a row on one branch.
        git(repo, "checkout", "--quiet", "-B", "develop", "main")
        normal = []
        functions = [
            ("shipping_cents", "def shipping_cents(total_cents):\n    return 0 if total_cents >= 5000 else 495\n",
             "self.assertEqual(shipping_cents(5000), 0)\n        self.assertEqual(shipping_cents(100), 495)"),
            ("vat_cents", "def vat_cents(net_cents):\n    return net_cents * 21 // 100\n",
             "self.assertEqual(vat_cents(1000), 210)"),
            ("round_to_5", "def round_to_5(cents):\n    return int(5 * round(cents / 5))\n",
             "self.assertEqual(round_to_5(1233), 1235)"),
            ("coupon_cents", "def coupon_cents(total_cents, code):\n    return 500 if code == 'WELCOME5' and total_cents >= 2500 else 0\n",
             "self.assertEqual(coupon_cents(3000, 'WELCOME5'), 500)\n        self.assertEqual(coupon_cents(1000, 'WELCOME5'), 0)"),
            ("items_count", "def items_count(lines):\n    return sum(qty for _, qty in lines)\n",
             "self.assertEqual(items_count([(1, 2), (3, 4)]), 6)"),
        ]
        pricing = PRICING_V1
        plan = []
        for i, (name, body, asserts) in enumerate(functions):
            plan.append(("code", name, body, asserts))
            if i in (0, 2, 4):
                plan.append(("docs", i))
            if i in (1, 3):
                plan.append(("script", i))
        plan = plan[:args.normal_runs]
        docs = README_V1
        script = "print('release notes')\n"
        for n, step in enumerate(plan, 1):
            prev = git(repo, "rev-parse", "HEAD")
            if step[0] == "code":
                _, name, body, asserts = step
                pricing = pricing + "\n\n" + body
                test = textwrap.dedent('''\
                    import unittest

                    from src.pricing import {name}


                    class {cls}Test(unittest.TestCase):
                        def test_{name}(self):
                            {asserts}


                    if __name__ == "__main__":
                        unittest.main()
                    ''').format(name=name, cls=name.title().replace("_", ""), asserts=asserts)
                head = commit(repo, "Add %s" % name, {"src/pricing.py": pricing, "tests/test_%s.py" % name: test})
                kind = "code change with its test"
            elif step[0] == "docs":
                docs = docs + "\nNote %d.\n" % step[1]
                head = commit(repo, "Docs note %d" % step[1], {"docs/README.md": docs})
                kind = "documentation"
            else:
                script = script + "print('section %d')\n" % step[1]
                head = commit(repo, "Release notes script %d" % step[1], {"scripts/release_notes.py": script})
                kind = "unprotected script"
            code, out, res, wall = run_guard(repo, prev, head, log_path, ref="normal-%02d" % n)
            normal.append({"n": n, "kind": kind, "result": res["result"], "cause": res["cause"], "exit": code,
                           "seconds": res["seconds"], "note": res.get("note", "")})

        # Report.
        print("\n" + "=" * 78)
        print("Seeded cases (blocking mode unless stated)")
        print("%-4s %-52s %-9s %-9s %-24s %-4s %s" % ("id", "case", "expected", "got", "cause", "exit", "check"))
        for r in rows:
            print("%-4s %-52s %-9s %-9s %-24s %-4d %s" % (r["id"], r["title"][:52], r["expected"], r["got"], r["cause"], r["exit"],
                                                       "OK" if r["ok"] else "MISMATCH"))

        print("\nNormal-change series: %d normal changes in a row on branch develop" % len(normal))
        for r in normal:
            print("  run %2d  %-26s %-13s %-20s exit %d  %.2f s%s" % (r["n"], r["kind"], r["result"], r["cause"], r["exit"], r["seconds"],
                                                                   "  note" if r["note"] else ""))
        false_stops = [r for r in normal if r["result"] not in ("PASSED", "EXEMPT", "OUT_OF_SCOPE") or r["exit"] != 0]

        with open(log_path, encoding="utf-8") as fh:
            log_lines = [l.rstrip("\n") for l in fh if l.strip()]
        all_secs = [r["seconds"] for r in rows if r["id"] != "E3"] + [r["seconds"] for r in normal]
        tested_secs = [r["seconds"] for r in normal if r["kind"] == "code change with its test"]
        stable = all(l.split("\t")[0] == "cg2" and len(l.split("\t")) == 19 for l in log_lines)
        skip_lines = [l for l in log_lines if "\tSKIPPED\t" in l]

        bad_cases = [r for r in rows if r["id"] in ("S1", "S2")]
        gaming_ids = ("S6", "S6s", "S7", "S8", "S11", "S12s", "S14", "F1",
                      "S15", "S16", "S17", "S18", "S18t", "S19", "S20", "S20f",
                      "S21", "S21c", "S22", "S23", "S23b", "S24", "S25")
        honest_ids = ("S3", "S9", "S12", "E6", "F2", "H1", "H2", "H3", "H4", "H5", "H6")
        gaming = [r for r in rows if r["id"] in gaming_ids]
        honest = [r for r in rows if r["id"] in honest_ids]
        print("\nFigures measured in this run")
        print("  catch:    %d of %d seeded bad cases stopped with a one-sentence cause (S1, S2)" % (
            sum(1 for r in bad_cases if r["ok"]), len(bad_cases)))
        print("  library:  %d of %d gaming cases stopped as expected (%s); %d of %d honest changes passed (%s)" % (
            sum(1 for r in gaming if r["ok"]), len(gaming), ", ".join(gaming_ids),
            sum(1 for r in honest if r["ok"]), len(honest), ", ".join(honest_ids)))
        print("  pass:     %d of %d normal runs went through, false stops: %d" % (
            len(normal) - len(false_stops), len(normal), len(false_stops)))
        print("  cost:     median guard time %.2f s over %d runs (E3 left out), %.2f s over the %d normal runs that ran tests, max %.2f s; budget 300 s" % (
            statistics.median(all_secs), len(all_secs), statistics.median(tested_secs) if tested_secs else 0.0,
            len(tested_secs), max(all_secs)))
        total_runs = len(rows) + len(normal)
        print("  record:   %d log lines for %d runs, stable format cg2 with 19 columns: %s, skip lines with who and why: %d" % (
            len(log_lines), total_runs, "yes" if stable else "NO", len(skip_lines)))
        all_ok = all(r["ok"] for r in rows) and not false_stops and len(log_lines) == total_runs and stable
        print("  overall: %s" % ("ALL CHECKS AS EXPECTED" if all_ok else "SOMETHING DIFFERED, SEE ABOVE"))

        print("\nThe log written by this run (tab-separated, columns in docs/how-it-works.md):")
        for l in log_lines:
            print("  " + l)

        leftover = git(repo, "worktree", "list").splitlines()
        print("\nworktrees left after all runs: %d (the main checkout only)" % len(leftover) if len(leftover) == 1
              else "\nWARNING: worktrees left: %s" % leftover)
        return 0 if all_ok else 1
    finally:
        if args.keep:
            print("\nkept the temporary folder: %s" % root)
        else:
            shutil.rmtree(root, ignore_errors=True)
            print("\nremoved the temporary folder: %s" % ("yes" if not os.path.exists(root) else "NO"))


if __name__ == "__main__":
    sys.exit(main())
