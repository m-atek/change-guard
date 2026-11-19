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
        self.assertIn('echo "reason<<${delim}"', text)
        line = next(l.strip() for l in text.splitlines() if l.strip().startswith("delim="))
        out = subprocess.run(["bash", "-c", line + '; printf "%s" "$delim"'], stdout=subprocess.PIPE, check=True).stdout.decode()
        self.assertRegex(out, r"^cg_[0-9a-f]{16}$")
        again = subprocess.run(["bash", "-c", line + '; printf "%s" "$delim"'], stdout=subprocess.PIPE, check=True).stdout.decode()
        self.assertNotEqual(out, again)


class I8GitHubExample(unittest.TestCase):
    """The copy-the-files workflow (version 0.3.1, finding I8 of the 0.3.0 audit)."""

    def test_i8_no_stored_token_guard_first_skip_through_outputs(self):
        text = read("ci", "github-actions.yml")
        self.assertIn("persist-credentials: false", text)
        order = [text.index(s) for s in ("- name: Check out", "- name: Take the guard from the base branch",
                                         "- name: Read the skip label and reason", "# Put the steps your tests need here",
                                         "- name: Run the change guard")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn('>> "$GITHUB_ENV"', text)
        self.assertIn("CHANGE_GUARD_SKIP_BY: ${{ steps.skip.outputs.requested == 'true' && steps.skip.outputs.by || '' }}", text)
        self.assertIn('if [ "$now" != "$GUARD_SHA" ]; then', text)

    def test_i8_the_hash_check_stops_a_changed_guard(self):
        script = step_script(read("ci", "github-actions.yml"), "Run the change guard")
        with tempfile.TemporaryDirectory() as d:
            tools = os.path.join(d, "change-guard")
            os.makedirs(tools)
            for name in ("change_guard.py", "cg_unittest_report.py"):
                with open(os.path.join(tools, name), "w") as fh:
                    fh.write("print('changed by a set-up step')\n")
            env = dict(os.environ, RUNNER_TEMP=d, GUARD_SHA="0" * 64, BASE_SHA="a", HEAD_SHA="b", PR_NUMBER="1",
                       GITHUB_STEP_SUMMARY=os.path.join(d, "s"))
            proc = subprocess.run(["bash", "-c", script], cwd=d, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("changed after they were taken", proc.stdout.decode())
        self.assertNotIn("changed by a set-up step", proc.stdout.decode())


class I9GitLabExample(unittest.TestCase):
    def test_i9_the_guard_and_the_base_come_from_the_tip_of_the_target_branch(self):
        text = read("ci", "gitlab-ci.yml")
        commands = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("CI_MERGE_REQUEST_DIFF_BASE_SHA", commands)
        self.assertIn('git fetch --quiet origin "$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"', commands)
        self.assertIn('--base "$CG_BASE"', commands)
        self.assertLess(commands.index("unset CHANGE_GUARD_API_TOKEN"), commands.index('python3 -I "$CG_DIR/change_guard.py"'))


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


HOSTILE = "import os\nopen(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'HOSTILE_RAN_' + %r), 'w').write('x')\n"


def hostile_checkout(folder):
    """A pull request checkout that brings its own json.py and sitecustomize.py (finding B1)."""
    for name in ("json", "sitecustomize", "os_helpers"):
        with open(os.path.join(folder, name + ".py"), "w") as fh:
            fh.write(HOSTILE % name)


def ran(folder):
    return sorted(n for n in os.listdir(folder) if n.startswith("HOSTILE_RAN_"))


class B1NoCodeFromTheCheckout(unittest.TestCase):
    """The action's own Python must never import a module from the pull request's checkout."""

    def test_every_python_call_in_the_action_and_ci_files_is_isolated(self):
        for parts in (("action.yml",), ("ci", "github-actions.yml"), ("ci", "gitlab-ci.yml"),
                      ("ci", "Jenkinsfile.change-guard"), ("ci", "azure-pipelines.change-guard.yml")):
            with self.subTest(file="/".join(parts)):
                text = read(*parts)
                calls = re.findall(r"\bpython3\b(?! -I\b)(?!\s*--version)[^\n]*", text)
                calls = [c for c in calls if not c.strip().startswith(("--version", "is ", "and ", "for "))]
                bad = [c for c in calls if re.match(r"python3\s+(-c|-|\"|\$|-B|\S+\.py)", c)]
                self.assertEqual(bad, [], "python3 without -I")

    def test_the_skip_step_does_not_run_a_json_py_from_the_checkout(self):
        script = step_script(read("action.yml"), "Read the skip label and reason")
        with tempfile.TemporaryDirectory() as d:
            hostile_checkout(d)
            output = os.path.join(d, "out")
            open(output, "w").close()
            env = dict(os.environ, CG_SKIP_LABEL="change-guard-skip", CG_LABELS='["other"]', CG_PR_NUMBER="7",
                       CG_PR_BODY="", GH_TOKEN="fake-token-for-the-test", GITHUB_OUTPUT=output,
                       PYTHONPATH=".")
            proc = subprocess.run(["bash", "-c", script], cwd=d, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(proc.returncode, 0, proc.stdout.decode())
            self.assertEqual(ran(d), [])
            self.assertIn("requested=false", open(output).read())

    def test_the_guard_step_does_not_run_a_json_py_from_the_checkout(self):
        script = step_script(read("action.yml"), "Run the change guard")
        with tempfile.TemporaryDirectory() as d:
            work = os.path.join(d, "checkout")
            tools = os.path.join(d, "tools")
            os.makedirs(work)
            os.makedirs(tools)
            hostile_checkout(work)
            with open(os.path.join(tools, "change_guard.py"), "w") as fh:
                fh.write("import json, sys\npath = sys.argv[sys.argv.index('--result-json') + 1]\n"
                         "json.dump({'result': 'STOPPED', 'cause': 'no-test', 'mode': 'block', 'blocks': True, 'log_line': 'cg2'}, open(path, 'w'))\n"
                         "sys.exit(1)\n")
            output = os.path.join(d, "out")
            open(output, "w").close()
            env = dict(os.environ, CG_TOOLS=tools, CG_MODE="block", CG_ENFORCE_LABEL="change-guard-enforce",
                       CG_LABELS='["change-guard-enforce"]', CG_BASE="main", CG_HEAD="change", CG_CONFIG="change-guard.json",
                       CG_WORKDIR=work, CG_PR_NUMBER="7", CHANGE_GUARD_SKIP_BY="", CHANGE_GUARD_SKIP_REASON="",
                       GITHUB_OUTPUT=output, GITHUB_STEP_SUMMARY=os.path.join(d, "summary"), PYTHONPATH=".")
            proc = subprocess.run(["bash", "-c", script], cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(proc.returncode, 1, proc.stdout.decode())
            self.assertEqual(ran(work), [])
            self.assertIn("blocks<<", open(output).read())

    def test_the_skip_values_reach_the_guard_only_when_a_skip_was_requested(self):
        text = read("action.yml")
        self.assertIn("CHANGE_GUARD_SKIP_BY: ${{ steps.skip.outputs.requested == 'true' && steps.skip.outputs.by || '' }}", text)
        self.assertIn("CHANGE_GUARD_SKIP_REASON: ${{ steps.skip.outputs.requested == 'true' && steps.skip.outputs.reason || '' }}", text)


if __name__ == "__main__":
    unittest.main()
