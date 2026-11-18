# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Tests for the CI files of version 0.3.0: the skip step's delimiter and the action's outputs.

Demo project, no real data. Run from the repository root:
    python3 -m unittest discover -s tests -v
Standard library only. The action's step runs in bash with a stand-in guard,
so no GitHub runner is needed.
"""

import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)


def read(*parts):
    with open(os.path.join(KIT, *parts), encoding="utf-8") as fh:
        return fh.read()


def step_script(text, name):
    """The run: | block of the step with this name, without its YAML indentation."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "- name: %s" % name)
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:] if line.strip() else "")
    return "\n".join(body) + "\n"


class SkipStepDelimiter(unittest.TestCase):
    def test_github_example_uses_a_random_delimiter(self):
        text = read("ci", "github-actions.yml")
        self.assertNotIn("CG_EOF", text)
        self.assertIn("CHANGE_GUARD_SKIP_REASON<<${delim}", text)
        line = next(l.strip() for l in text.splitlines() if l.strip().startswith("delim="))
        out = subprocess.run(["bash", "-c", line + '; printf "%s" "$delim"'], stdout=subprocess.PIPE, check=True).stdout.decode()
        self.assertRegex(out, r"^cg_[0-9a-f]{16}$")
        again = subprocess.run(["bash", "-c", line + '; printf "%s" "$delim"'], stdout=subprocess.PIPE, check=True).stdout.decode()
        self.assertNotEqual(out, again)


class ActionOutputs(unittest.TestCase):
    """The action's guard step, run with a stand-in guard that writes a result file and exits."""

    def run_step(self, exit_code, blocks_in_file, result="PASSED"):
        script = step_script(read("action.yml"), "Run the change guard")
        with tempfile.TemporaryDirectory() as d:
            tools = os.path.join(d, "tools")
            os.makedirs(tools)
            with open(os.path.join(tools, "change_guard.py"), "w") as fh:
                fh.write(textwrap.dedent('''\
                    import json, sys
                    path = sys.argv[sys.argv.index("--result-json") + 1]
                    with open(path, "w") as fh:
                        json.dump({"result": %r, "cause": "ok", "mode": "block", "blocks": %r, "log_line": "cg2\\tx"}, fh)
                    sys.exit(%d)
                    ''' % (result, blocks_in_file, exit_code)))
            output = os.path.join(d, "github_output")
            open(output, "w").close()
            env = dict(os.environ, CG_TOOLS=tools, CG_MODE="block", CG_ENFORCE_LABEL="", CG_LABELS="null",
                       CG_BASE="main", CG_HEAD="change", CG_CONFIG="change-guard.json", CG_WORKDIR=d,
                       CG_PR_NUMBER="7", CHANGE_GUARD_SKIP_BY="", CHANGE_GUARD_SKIP_REASON="",
                       GITHUB_OUTPUT=output, GITHUB_STEP_SUMMARY=os.path.join(d, "summary"))
            proc = subprocess.run(["bash", "-c", script], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            with open(output) as fh:
                text = fh.read()
        values = {k: v for k, _, v in re.findall(r"^([\w-]+)<<(cg_[0-9a-f]{16})\n(.*)\n\2$", text, re.M)}
        return proc.returncode, values, proc.stdout.decode()

    def test_blocks_follows_the_exit_code(self):
        code, values, out = self.run_step(1, False)
        self.assertEqual(code, 1, out)
        self.assertEqual(values["blocks"], "true")
        self.assertIn("does not match the guard's exit code", out)

    def test_a_consistent_result_gives_no_warning(self):
        for exit_code, blocks in ((0, False), (1, True)):
            with self.subTest(exit_code=exit_code):
                code, values, out = self.run_step(exit_code, blocks, "PASSED" if exit_code == 0 else "STOPPED")
                self.assertEqual(code, exit_code, out)
                self.assertEqual(values["blocks"], "true" if blocks else "false")
                self.assertEqual(values["result"], "PASSED" if exit_code == 0 else "STOPPED")
                self.assertNotIn("does not match", out)

    def test_a_result_file_that_claims_blocking_cannot_pass_as_blocking(self):
        code, values, out = self.run_step(0, True)
        self.assertEqual(code, 0, out)
        self.assertEqual(values["blocks"], "false")
        self.assertIn("does not match", out)


if __name__ == "__main__":
    unittest.main()
