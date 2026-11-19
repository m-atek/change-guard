#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Change guard: a pull request check that the tests of a change really test that change.

Rule: a change to protected paths must bring a new or changed test file, and
those test files must fail on the base commit's code and pass on the head.

How it judges a change (version 0.3.3):
  1. It reads its configuration from the base commit (the target branch's
     rules), never from the change it judges. If that configuration cannot be
     loaded, a recorded skip or a change that only repairs it can still pass.
  2. It lists the files changed between the merge base of BASE and HEAD, and HEAD.
  3. Changes that touch only exempt files pass untouched (no test runs).
     Pure renames, whitespace in Python files that leaves the syntax tree as
     it was, and files that were already generated on the base are exempt too.
  4. A change to a protected path with no new or changed test file is stopped.
  5. The changed test files run on a clean checkout of HEAD: they must pass
     (one retry for a flaky head run).
  6. The same test files (the head's version), the test_support files, the
     files the change adds outside the protected paths and the edited files
     that are test material are laid over a clean checkout of the base in a
     temporary worktree and run there: they must fail. With a
     per-test report, each test's base result is classified (failed by
     assertion, errored because a name the change adds is missing, errored for
     another reason, passed, skipped, not collected), and a base run that only
     errors for an unrelated reason is not counted as proof.
  7. A passing verdict needs a second base run with the same result.
  8. For Python, each function the change adds (or whose signature gains a
     parameter) gets a neutral body ("return None") in a third worktree, and
     the changed tests must notice.
  9. Notes (never a stop): assertions removed, tests deleted, skip markers
     added, snapshot files changed, the new code mocked in its own test, the
     guard's own files changed.
 10. A documented skip step (who and why, both required) passes the change and
     is recorded.
 11. Every run appends exactly one line to a log in a stable, tab-separated
     format, also when the guard itself fails; the exceptions are a run that
     ends as ERROR log-busy (another run held the log too long) and a log file
     that cannot be written.
 12. The test and set-up commands have a time budget, with a clear message when
     it is exceeded; the guard's own git commands and report reading are not
     counted, and the wait for the log lock has its own limit.
 13. The tests run with a reduced environment, and a run in which they changed
     the log, the guard's files, the CI platform's control files or the
     repository's hooks, git configuration or info folder ends as ERROR.
 14. Git runs with hooks off and without user or system configuration; every
     worktree is made before the first test runs, the guard's own changes are
     committed in it, and it is checked before each run there.

Needs only git and the Python 3 standard library (Python 3.8 or later).
Run "python3 change_guard.py --help" for the options. README.md explains the
configuration, the log format and the known limits.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import errno
import fnmatch
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tokenize
import traceback
import xml.etree.ElementTree as ElementTree

VERSION = "0.3.3"
LOG_VERSION = "cg2"
HERE = os.path.dirname(os.path.abspath(__file__))

# Results. PASSED, EXEMPT, OUT_OF_SCOPE and SKIPPED let the change through.
PASSED = "PASSED"
EXEMPT = "EXEMPT"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
SKIPPED = "SKIPPED"
STOPPED = "STOPPED"
TIMEOUT = "TIMEOUT"
ERROR = "ERROR"
LETS_THROUGH = {PASSED, EXEMPT, OUT_OF_SCOPE, SKIPPED}

REPORT_FORMATS = {
    "none": None,
    "unittest-json": "jsonl",
    "junit-xml": "xml",
    "go-json": "jsonl",
    "jest-json": "json",
    "rspec-json": "json",
    # Version 0.3.0: the TRX file of dotnet test (--logger trx).
    "dotnet-trx": "trx",
}

DEFAULTS = {
    "protected": [],
    "exempt": [],
    "tests": [],
    "test_support": [],
    "test_command": None,
    "setup_command": None,
    "time_budget_seconds": 300,
    "on_timeout": "stop",
    "mode": "report",
    "log_file": ".change-guard/runs.log",
    "skip_reason_min_length": 10,
    "suspect_base_failure_patterns": [
        "SyntaxError",
        "IndentationError",
        "command not found",
        "No such file or directory",
        "Cannot find module",
        "cannot find package",
        "Could not resolve",
        "compilation failed",
        "BUILD FAILED",
        "[build failed]",
        "Compilation failed",
        # Version 0.3.2 (RT-N6): the usual messages of compilers and runtimes for a
        # name that does not exist, so that without a per-test report a test that
        # only fails because the new code is missing on the base gets a note.
        "cannot find symbol",
        "is not a function",
        "is not defined",
        "has no attribute",
        "cannot import name",
        "No module named",
        "unexpected keyword argument",
        "does not provide an export named",
        "has no exported member",
        "Unresolved reference",
        "undefined: ",
        "has no field or method",
        "NoSuchMethodError",
        "does not contain a definition for",
        "error CS0103",
        "undefined method",
        "uninitialized constant",
        "Call to undefined",
        "' in scope",
        "has no member",
    ],
    "output_tail_lines": 12,
    "inconclusive_exit_codes": [],
    # Version 0.2.0 keys. All optional.
    "report_format": "none",
    "report_path": None,
    "base_error_policy": "probe",
    "probe": "auto",
    "probe_command": None,
    "probe_scope": "each",
    "probe_ignore": ["__repr__", "__str__", "_log*"],
    "probe_time_budget_seconds": 120,
    "base_repeats": 2,
    "head_retries": 1,
    "errored_counts_as_proof": True,
    "missing_symbol_patterns": [],
    "environment_error_patterns": [],
    "overlay_added_files": True,
    "auto_exempt": ["whitespace", "rename", "generated"],
    "generated_markers": ["Code generated", "DO NOT EDIT", "@generated", "<auto-generated"],
    "notes": True,
    "check_edited_tests": False,
    "snapshot_patterns": ["**/__snapshots__/**", "**/*.snap", "**/*.stderr", "**/*.golden",
                          "**/testdata/**/*.golden", "**/*.approved.*"],
    # Version 0.2.1 keys. All optional.
    "pass_env": [],
    "guard_files": ["**/change_guard.py", "**/cg_unittest_report.py", ".github/workflows/change-guard.yml",
                    ".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS", ".gitlab-ci.yml", "Jenkinsfile",
                    "azure-pipelines.yml", ".gitattributes", "**/.gitattributes"],
}

# The environment of the test and setup commands (version 0.2.1). The tests come
# from the change being judged, so they get these plain variables, the ones the
# configuration names in pass_env, and nothing else: no CI token, no CI output
# or environment file, no secret the job may hold.
SAFE_ENV = (
    # The shell and the locale.
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TERM", "TZ", "TMPDIR", "TMP", "TEMP", "CI",
    # Where the toolchains live (paths and switches, never credentials).
    "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING", "PYTHONUTF8", "PYTHONHASHSEED", "VIRTUAL_ENV",
    "JAVA_HOME", "GRADLE_USER_HOME", "MAVEN_HOME", "M2_HOME", "GOPATH", "GOROOT", "GOCACHE", "GOMODCACHE",
    "NODE_PATH", "GEM_HOME", "GEM_PATH", "BUNDLE_PATH", "CARGO_HOME", "RUSTUP_HOME", "DOTNET_ROOT",
    # Windows agents.
    "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR",
)
SAFE_ENV_PREFIXES = ("LC_",)
# Never passed, even when pass_env names them: the CI platform's control files
# and the job's own tokens.
NEVER_PASSED_ENV = (
    "GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY", "GITHUB_TOKEN", "GH_TOKEN",
    "ACTIONS_RUNTIME_TOKEN", "ACTIONS_RUNTIME_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_CACHE_URL", "ACTIONS_RESULTS_URL", "CI_JOB_TOKEN", "CI_JOB_JWT", "CI_JOB_JWT_V1", "CI_JOB_JWT_V2",
    "CI_REGISTRY_PASSWORD", "CI_DEPLOY_PASSWORD", "SYSTEM_ACCESSTOKEN", "CHANGE_GUARD_API_TOKEN",
    # Version 0.3.1 (M13): these GitLab variables hold the job token too.
    "CI_REPOSITORY_URL", "CI_DEPENDENCY_PROXY_PASSWORD", "CI_REGISTRY_USER_PASSWORD",
)
# Files the tests must not change while the guard runs, taken from the guard's own environment.
CI_CONTROL_FILES = ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY")

PLACEHOLDERS = ("{files}", "{dirs}", "{classes}", "{gradle_tests}", "{classes_csv}", "{dotnet_filter}", "{names_regex}")
JVM_SOURCE_ROOT = re.compile(r"(?:^|/)src/[^/]+/(?:java|kotlin|groovy|scala)/(.+)\.(?:java|kt|groovy|scala)$")

LOG_COLUMNS = [
    "log_version", "time_utc", "result", "cause", "mode", "ref", "base", "head",
    "seconds", "protected_files", "test_files", "skipped_by", "skip_reason", "message",
    "tests_proof", "tests_new_symbol", "tests_other", "probe", "notes",
]

# Error messages that name a missing symbol: one capture group for the name.
# Data, not code. Since version 0.3.0 the patterns for Jest, Vitest, javac (via
# Maven and Gradle), Kotlin (via Gradle), go test, the C# compiler (via dotnet
# test), PHPUnit, RSpec and Swift (swift test on Linux) were matched against
# real output on GitHub's hosted Linux runner (tests/data/polyglot/,
# docs/languages.md); the others (plain Node.js ES modules, TypeScript's own
# compiler) still come from general knowledge of the messages, so check them
# against one real error from your own runner (docs/edge-cases.md).
MISSING_SYMBOL_PATTERNS = [
    r"cannot import name '(\w+)'",
    r"has no attribute '(\w+)'",
    r"does not have the attribute '(\w+)'",
    r"name '(\w+)' is not defined",
    r"No module named '([\w.]+)'",
    # A dictionary key or a vars()/globals() lookup (version 0.3.1, findings I2 and D6).
    r"KeyError: '(\w+)'",
    # pytest: a fixture the base does not have (version 0.3.3, C-N1).
    r"fixture '(\w+)' not found",
    r"got an unexpected keyword argument '(\w+)'",
    r"(\w+)\(\) takes (?:from )?\d+ (?:to \d+ )?positional arguments? but \d+ (?:was|were) given",
    r"(\w+)\(\) missing \d+ required (?:positional|keyword-only) arguments?",
    # Jest: "formatPrice is not a function"; Vitest: "(0 , formatPrice) is not a function".
    r"(\w+)\)? is not a function",
    r"does not provide an export named '(\w+)'",
    r"has no exported member '(\w+)'",
    r"Cannot find module '([^']+)'",
    r"\b(\w+) is not defined",
    r"undefined: (?:\w+\.)?(\w+)",
    r"has no field or method (\w+)",
    r"cannot find symbol[\s\S]{0,200}?symbol:\s+\w+\s+(\w+)",
    r"Unresolved reference:? '?(\w+)",
    r"NoSuchMethodError: .*\.(\w+)\(",
    r"error CS0103: The name '(\w+)'",
    r"error CS0117: .*? does not contain a definition for '(\w+)'",
    r"error CS1061: .*?does not contain a definition for '(\w+)'",
    r"undefined method [`'](\w+)'",
    r"uninitialized constant (?:\w+::)*(\w+)",
    r"Call to undefined (?:function|method) [\w\\:]*?(\w+)\(",
    r"cannot find '(\w+)' in scope",
    r"has no member '(\w+)'",
]

ENVIRONMENT_ERROR_PATTERNS = [
    "FileNotFoundError", "ENOENT", "Connection refused", "timed out", "No space left",
    "Permission denied", "command not found",
]

FILE_ERROR_HINTS = ("No such file", "FileNotFoundError", "ENOENT", "not found", "does not exist", "cannot open")

ASSERTION_TYPE_RX = re.compile(r"(Assertion|Expectation|ComparisonFailure|AssertFailed)")

DEFINITION_PATTERNS = [re.compile(p) for p in (
    r"^\s*(?:async\s+)?def\s+(?:self\.)?(\w+)",
    r"^\s*class\s+(\w+)",
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)",
    r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=",
    r"^\s*export\s+(?:abstract\s+)?(?:class|interface|type|enum)\s+(\w+)",
    r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)",
    r"^\s*type\s+(\w+)",
    r"^\s*(?:(?:public|private|protected|internal|static|final|override|virtual|abstract|async|synchronized)\s+)+[\w<>\[\],.?]+\s+(\w+)\s*\(",
    r"^\s*(?:(?:public|private|protected)\s+)?(?:static\s+)?function\s+(\w+)",
    r"^\s*(?:(?:private|internal|public|override)\s+)*fun\s+(?:<[^>]*>\s*)?(\w+)",
    # Version 0.3.1 (findings I2 and I5 of the 0.3.0 audit): more declaration forms.
    # Classes and other types in Java, Kotlin, C#, Swift, TypeScript and PHP.
    r"^\s*(?:(?:public|private|protected|internal|abstract|final|sealed|static|open|data|export|default|partial|readonly|fileprivate)\s+)*(?:class|interface|enum|record|struct|object|protocol|trait)\s+(\w+)",
    # A Java or C# method without an access word: "long withTax(long cents) {".
    r"^\s*(?:@\w+\s+)*[\w<>\[\],.?]+\s+(\w+)\s*\([^;]*\)\s*(?:throws\s+[\w.,\s]+)?\{?\s*$",
    # Constants and fields: Java and C# ("public static final int MAX = 5"), PHP ("const MAX = 5").
    r"^\s*(?:(?:public|private|protected|internal|static|final|const|readonly|volatile|transient)\s+)+[\w<>\[\],.?]+\s+(\w+)\s*=",
    r"^\s*(?:(?:public|private|protected|final)\s+)*const\s+(\w+)\s*=",
    # Kotlin and Swift properties.
    r"^\s*(?:(?:private|internal|public|protected|const|static|lazy|override|open|fileprivate|lateinit)\s+)*(?:val|var|let)\s+(\w+)",
    # Swift functions with modifiers.
    r"^\s*(?:(?:public|private|internal|fileprivate|open|static|class|final|override|mutating|@\w+)\s+)+func\s+(\w+)",
    # JavaScript and TypeScript class methods, and CommonJS exports.
    r"^\s*(?:(?:static|async|get|set|public|private|protected|readonly)\s+)*(\w+)\s*\([^)]*\)\s*(?::\s*[\w<>\[\],.| ]+)?\{",
    r"^\s*(?:module\.)?exports\.(\w+)\s*=",
)]
# Words that the patterns above can capture but that never name a definition.
DEFINITION_KEYWORDS = frozenset((
    "if", "for", "while", "switch", "catch", "return", "new", "else", "function", "do", "try", "with",
    "synchronized", "super", "this", "throw", "typeof", "await", "yield", "case", "using", "lock",
    "foreach", "fixed", "sizeof", "nameof", "when", "match", "elif", "guard", "defer", "repeat", "assert",
))

ASSERT_LINE_RX = re.compile(r"(?:\bassert|\bexpect\s*\(|\bshould\b|XCTAssert|\bAssert\.|\$this->assert|\bt\.Error|\bt\.Fatal|\brequire\.)")
SKIP_MARKER_RX = re.compile(r"(@skip|skipIf|skipUnless|unittest\.skip|pytest\.mark\.skip|xfail|expectedFailure|\.skip\(|\bxit\(|\bxdescribe\(|\bt\.Skip|@Disabled|\[Ignore\]|markTestSkipped|XCTSkip|\.todo\()")
TEST_DEF_RX = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)|^\s*func\s+(Test\w+)|^\s*(?:it|test)\s*\(\s*['\"]([^'\"]+)['\"]")
MOCK_RX = re.compile(r"(patch|[Mm]ock|spyOn|stub|monkeypatch)")


class GuardStop(Exception):
    """Ends the evaluation early with a result, a cause code and one sentence."""

    def __init__(self, result, cause, message, hint=""):
        super().__init__(message)
        self.result = result
        self.cause = cause
        self.message = message
        self.hint = hint


class GuardCancelled(Exception):
    """A CI cancel (SIGTERM) or Ctrl-C during the run (version 0.3.1, M3 and D12 of the 0.3.0 audit)."""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def _on_signal(signum, frame):
    raise GuardCancelled(signum)


class BudgetExceeded(Exception):
    def __init__(self, phase):
        super().__init__(phase)
        self.phase = phase


# --------------------------------------------------------------------------
# Path patterns
# --------------------------------------------------------------------------

def glob_to_regex(pattern):
    """Translate a path pattern into a regular expression.

    "**" matches any number of folders, "*" matches within one folder name,
    "?" matches one character. A pattern without a slash matches the file name
    in any folder, the way .gitignore does. Paths use forward slashes.

    Since version 0.3.1 a pattern that names a folder also matches everything
    inside it, as in .gitignore: "src", "src/" and "./src/**" all protect the
    files under src/ (finding I7 of the 0.3.0 audit).
    """
    pat = pattern.strip()
    while pat.startswith("./"):
        pat = pat[2:]
    pat = pat.lstrip("/")
    if pat.endswith("/"):
        pat = pat.rstrip("/") + "/**"
    anywhere = "/" not in pat
    out = []
    i = 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    body = "".join(out)
    if anywhere:
        body = "(?:.*/)?" + body
    # re.S and \Z: a file name that holds a line feed is still matched (version 0.3.2, RC-N5).
    return re.compile("^" + body + "(?:/.*)?\\Z", re.S)


def matches_any(path, compiled):
    return any(rx.match(path) for rx in compiled)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def _config_error(text):
    return GuardStop(ERROR, "config", text)


def parse_config(data, where):
    """The configuration from the bytes of a JSON file; where names the file in messages."""
    try:
        raw = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise _config_error("The configuration file %s is not UTF-8 text, so the guard cannot run." % where)
    except json.JSONDecodeError as exc:
        raise _config_error("The configuration file %s is not valid JSON (line %d), so the guard cannot run." % (where, exc.lineno))
    if not isinstance(raw, dict):
        raise _config_error("The configuration file %s must hold one JSON object, so the guard cannot run." % where)
    return validate_config(raw)


def load_config(path):
    """The configuration from a file on disk (used for a path outside the repository)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        raise _config_error("The configuration file %s does not exist, so the guard cannot run." % path)
    return parse_config(data, path)


def load_config_from_commits(repo, base, head, rel_path, say, state):
    """The configuration as committed on the base commit: the target branch's rules.

    The change being judged never supplies its own rules. Only when the base
    has no configuration at all (the pull request that installs the guard) is
    the head's copy used, and the output and the log say so.
    """
    data = show_file(repo, base, rel_path)
    if data is not None:
        say("config: %s from the base commit %s" % (rel_path, short(base)))
        return parse_config(data, "%s on the base commit" % rel_path)
    data = show_file(repo, head, rel_path)
    if data is None:
        raise _config_error("The configuration file %s is on neither the base nor the head commit, so the guard cannot run." % rel_path)
    say("config: %s is not on the base commit %s, so the head's copy was used; this is only right for the change that installs the guard" % (rel_path, short(base)))
    add_note(state, "config-from-head", "the base commit has no %s, so this run used the configuration from the change itself" % rel_path)
    return parse_config(data, "%s on the head commit" % rel_path)


def normal_mode(value):
    """A mode as given by a person: report, Report and ' block ' are the same (version 0.3.1)."""
    return value.strip().lower() if isinstance(value, str) else value


def validate_config(raw):
    unknown = [k for k in raw if k not in DEFAULTS and not k.startswith("_")]
    if unknown:
        raise _config_error("The configuration file has unknown keys (%s), so the guard refuses to guess what was meant." % ", ".join(sorted(unknown)))
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if not k.startswith("_")})
    cfg["mode"] = normal_mode(cfg["mode"])
    for key in ("protected", "exempt", "tests", "test_support", "suspect_base_failure_patterns",
                "probe_ignore", "missing_symbol_patterns", "environment_error_patterns",
                "auto_exempt", "generated_markers", "snapshot_patterns", "pass_env", "guard_files"):
        if not isinstance(cfg[key], list) or not all(isinstance(x, str) for x in cfg[key]):
            raise _config_error("The configuration key %s must be a list of strings, so the guard cannot run." % key)
    if not cfg["protected"]:
        raise _config_error("The configuration names no protected paths, so the guard has nothing to protect.")
    if not cfg["tests"]:
        raise _config_error("The configuration names no test file patterns, so the guard cannot tell a test from code.")
    if not isinstance(cfg["test_command"], str) or not any(ph in cfg["test_command"] for ph in PLACEHOLDERS):
        raise _config_error("The test_command must be a string that contains {files}, {dirs}, {classes}, {classes_csv}, {gradle_tests}, {dotnet_filter} or {names_regex}, so the guard can run only the changed test files.")
    if not isinstance(cfg["inconclusive_exit_codes"], list) or not all(isinstance(x, int) for x in cfg["inconclusive_exit_codes"]):
        raise _config_error("The configuration key inconclusive_exit_codes must be a list of whole numbers, so the guard cannot run.")
    choices = {
        "mode": ("report", "block"),
        "on_timeout": ("stop", "pass"),
        "report_format": tuple(REPORT_FORMATS),
        "base_error_policy": ("probe", "note", "stop"),
        "probe": ("auto", "off", "python", "command"),
        "probe_scope": ("each", "any"),
    }
    for key, allowed in choices.items():
        if cfg[key] not in allowed:
            if key == "mode":
                # A mistyped mode fails closed (version 0.3.1, finding I1).
                stop = _config_error("The configuration key mode must be report or block, so the guard cannot run with %r; it fails the check until the value is fixed." % cfg[key])
                stop.fail_closed = True
                raise stop
            raise _config_error("The configuration key %s must be one of %s, so the guard cannot run with %r." % (key, ", ".join(allowed), cfg[key]))
    bad = [x for x in cfg["auto_exempt"] if x not in ("whitespace", "rename", "generated")]
    if bad:
        raise _config_error("The configuration key auto_exempt accepts only whitespace, rename and generated, so the guard cannot run with %s." % ", ".join(bad))
    if cfg["check_edited_tests"] not in (True, False, "stop"):
        raise _config_error("The configuration key check_edited_tests must be true, false or \"stop\", so the guard cannot run.")
    for key in ("errored_counts_as_proof", "overlay_added_files", "notes"):
        if not isinstance(cfg[key], bool):
            raise _config_error("The configuration key %s must be true or false, so the guard cannot run." % key)
    if cfg["report_format"] != "none" and not cfg["report_path"] and "{report}" not in cfg["test_command"] and "CHANGE_GUARD_REPORT" not in cfg["test_command"]:
        raise _config_error("The report_format is %s but the test_command does not write the report to {report} and no report_path is set, so the guard would find no report." % cfg["report_format"])
    if cfg["report_path"] is not None and not isinstance(cfg["report_path"], str):
        raise _config_error("The configuration key report_path must be a path or null, so the guard cannot run.")
    if cfg["report_path"]:
        # The guard deletes this path before each run, so it must stay inside the worktree.
        parts = cfg["report_path"].replace("\\", "/").split("/")
        if (cfg["report_path"].startswith(("/", "\\")) or ":" in parts[0] or ".." in parts
                or all(p in ("", ".") for p in parts)):
            raise _config_error("The configuration key report_path must name a folder or file inside the repository, so the guard cannot run.")
    forbidden = [n for n in cfg["pass_env"] if n in NEVER_PASSED_ENV]
    if forbidden:
        raise _config_error("The configuration key pass_env names %s, which the guard never passes to the tests, so the guard cannot run." % ", ".join(forbidden))
    if cfg["probe"] == "command" and not isinstance(cfg["probe_command"], str):
        raise _config_error("The probe is set to command but probe_command is not set, so the guard cannot run the probe.")
    # Version 0.3.2 (the rest of D11): a number must be a JSON number, not a string
    # or true/false; a time budget is above zero and finite; a count is a whole
    # number of at least zero.
    for key in ("time_budget_seconds", "probe_time_budget_seconds"):
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise _config_error("The configuration key %s must be a number of seconds above zero, so the guard cannot run with %s." % (key, json.dumps(value)))
        cfg[key] = float(value)
    for key in ("skip_reason_min_length", "output_tail_lines", "base_repeats", "head_retries"):
        value = cfg[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or value != int(value) or value < 0):
            raise _config_error("The configuration key %s must be a whole number of zero or more, so the guard cannot run with %s." % (key, json.dumps(value)))
        cfg[key] = int(value)
    if cfg["base_repeats"] not in (1, 2) or cfg["head_retries"] not in (0, 1):
        raise _config_error("The configuration keys base_repeats (1 or 2) and head_retries (0 or 1) are out of range, so the guard cannot run.")
    try:
        cfg["_missing_rx"] = [re.compile(p) for p in MISSING_SYMBOL_PATTERNS + cfg["missing_symbol_patterns"]]
    except re.error as exc:
        raise _config_error("A pattern in missing_symbol_patterns is not a valid regular expression (%s), so the guard cannot run." % exc)
    cfg["_env_patterns"] = ENVIRONMENT_ERROR_PATTERNS + cfg["environment_error_patterns"]
    return cfg


# --------------------------------------------------------------------------
# Git helpers
# --------------------------------------------------------------------------

# Every git command of the guard runs with hooks switched off and without the
# user's or the system's git configuration (version 0.2.2). The tests of the change
# run as the same user, so they could write a hook or a setting there; only the
# repository's own configuration is read, and the tamper check watches it
# (RepoWatch). safe.directory is the one setting taken over from the user's and
# the system's configuration, and only when git refuses a checkout owned by
# another user (some containers do that), so such a checkout still works.
_GIT = {"env": None, "args": None, "safe_loaded": False}
_REPO_WATCHES = []


def _git_setup():
    if _GIT["env"] is not None:
        return
    env = dict(os.environ)
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "HOME": os.devnull,
                "XDG_CONFIG_HOME": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0"})
    # safe.bareRepository=explicit (version 0.3.2, RC-N9): a folder of the checkout
    # that looks like a bare repository (HEAD, objects/, refs/ written by a pull
    # request) is never taken for the repository. Git before 2.38 ignores it.
    _GIT["env"], _GIT["args"] = env, ["-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
                                      "-c", "safe.bareRepository=explicit"]


def _load_safe_directories():
    """The safe.directory values of the system and the user, as protected command-line settings."""
    _GIT["safe_loaded"] = True
    try:
        proc = subprocess.run(["git", "config", "--show-scope", "--get-all", "safe.directory"], cwd=os.sep,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    values = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        scope, _, value = line.partition("\t")
        if scope in ("system", "global") and value.strip() and value not in values:
            values.append(value)
    for value in values:
        _GIT["args"] += ["-c", "safe.directory=" + value]
    return bool(values)


def git(repo, *args, check=True, env=None):
    _git_setup()
    # Before every git command: the repository's hooks, configuration and info
    # folder must be as they were when the run started (RepoWatch).
    for watch in list(_REPO_WATCHES):
        changed = watch.check()
        if changed and watch.strict:
            raise GuardStop(ERROR, "tampered", MESSAGES["tampered"].format(files=", ".join(changed)), HINTS["tampered"])
    run_env = _GIT["env"] if not env else dict(_GIT["env"], **env)
    while True:
        proc = subprocess.run(
            ["git"] + _GIT["args"] + ["-C", repo] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=run_env,
        )
        if (proc.returncode != 0 and not _GIT["safe_loaded"] and b"dubious ownership" in proc.stderr
                and _load_safe_directories()):
            continue
        break
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        detail = err[-1] if err else "no message"
        shown = [a for a in args if not (a.startswith(("core.", "commit.", "gc.", "maintenance.")) or a == "-c")]
        raise GuardStop(ERROR, "git", "The git command 'git %s' failed (%s), so the guard cannot judge this change." % (" ".join(shown[:3]), detail))
    return proc


def git_common_dir(repo):
    """The repository's .git folder (the common one, for a linked worktree), read without git where possible."""
    dot_git = os.path.join(repo, ".git")
    if os.path.isdir(dot_git) and not os.path.islink(dot_git):
        return os.path.normpath(dot_git)
    common = git(repo, "rev-parse", "--git-common-dir").stdout.decode("utf-8", "replace").strip()
    return os.path.normpath(os.path.join(repo, common))


class RepoWatch:
    """The repository's hooks, git configuration and info folder, as they were before the tests ran.

    check() compares them with that state; anything the tests added, changed or
    removed is put back, and the changed paths are returned (and kept in
    .changed). While strict is true, git() then ends the run as ERROR tampered.
    """

    NAMES = ("config", "config.worktree", "hooks", "info")

    def __init__(self, repo):
        self.root = git_common_dir(repo)
        self.repo = repo
        self.snapshot = self._take()
        self.changed = []
        self.strict = True

    def _take(self):
        snap = {}
        for name in self.NAMES:
            self._add(os.path.join(self.root, name), name, snap)
        return snap

    def _add(self, full, rel, snap):
        if rel == "info/refs":
            # Written by git's own housekeeping (update-server-info during gc), never read
            # by a local checkout (version 0.3.1, D5 of the 0.3.0 audit).
            return
        try:
            st = os.lstat(full)
        except OSError:
            return
        if stat.S_ISLNK(st.st_mode):
            snap[rel] = ("link", os.readlink(full))
        elif stat.S_ISDIR(st.st_mode):
            snap[rel] = ("dir", stat.S_IMODE(st.st_mode))
            try:
                children = sorted(os.listdir(full))
            except OSError:
                children = []
            for child in children:
                self._add(os.path.join(full, child), rel + "/" + child, snap)
        else:
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
            except OSError:
                data = None
            snap[rel] = ("file", stat.S_IMODE(st.st_mode), data)

    def _shown(self, rel):
        full = os.path.join(self.root, *rel.split("/"))
        try:
            return os.path.relpath(full, self.repo).replace(os.sep, "/")
        except ValueError:
            return full

    def check(self):
        now = self._take()
        if now == self.snapshot:
            return []
        changed = sorted(r for r in set(now) | set(self.snapshot) if now.get(r) != self.snapshot.get(r))
        self._restore(now)
        shown = [self._shown(r) for r in changed]
        for item in shown:
            if item not in self.changed:
                self.changed.append(item)
        return shown

    def _restore(self, now):
        def remove(full):
            try:
                if os.path.isdir(full) and not os.path.islink(full):
                    shutil.rmtree(full, ignore_errors=True)
                else:
                    os.remove(full)
            except OSError:
                pass
        for rel in sorted(set(now) - set(self.snapshot), key=len, reverse=True):
            remove(os.path.join(self.root, *rel.split("/")))
        for rel in sorted(self.snapshot):
            want, have = self.snapshot[rel], now.get(rel)
            if have == want:
                continue
            full = os.path.join(self.root, *rel.split("/"))
            try:
                if have is not None and (have[0] != want[0] or want[0] == "link"):
                    remove(full)
                if want[0] == "dir":
                    os.makedirs(full, exist_ok=True)
                    os.chmod(full, want[1])
                elif want[0] == "link":
                    os.symlink(want[1], full)
                elif want[2] is not None:
                    if have is not None and have[0] == "file":
                        # A file the tests made unreadable or read-only is made
                        # writable again first, or it could not be put back.
                        os.chmod(full, want[1] | stat.S_IRUSR | stat.S_IWUSR)
                    with open(full, "wb") as fh:
                        fh.write(want[2])
                    os.chmod(full, want[1])
            except OSError:
                pass


SEAL_MESSAGE = "Prepared by the change guard"
SEAL_ENV = {"GIT_AUTHOR_NAME": "change-guard", "GIT_AUTHOR_EMAIL": "change-guard@localhost",
            "GIT_COMMITTER_NAME": "change-guard", "GIT_COMMITTER_EMAIL": "change-guard@localhost",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000"}


def seal_commit(worktree, paths=(), amend=False):
    """Commit what the guard wrote into a throwaway worktree, with one neutral message.

    Every worktree gets such a commit (the head's is empty), so git status is
    clean in all of them and git log -1 shows the same message (version 0.2.2).
    Returns the new commit.
    """
    if paths:
        git(worktree, "add", "--force", "--", *paths)
    cmd = ["-c", "commit.gpgsign=false", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
           "-c", "core.safecrlf=false", "-c", "core.abbrev=40", "commit", "--no-verify", "--allow-empty",
           "-m", SEAL_MESSAGE]
    if amend:
        cmd.append("--amend")
    out = git(worktree, *cmd, env=SEAL_ENV).stdout.decode("utf-8", "replace")
    m = re.search(r"^\[[^\]]*?\b([0-9a-f]{40,64})\]", out, re.M)
    if m:
        return m.group(1)
    return git(worktree, "rev-parse", "HEAD").stdout.decode().strip()


def _file_digest(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


class WorktreeSeal:
    """What the guard put into a throwaway worktree, checked before each run there.

    The tracked files must be the guard's commit (git status shows nothing and
    HEAD is that commit), the files the guard wrote must hash as written, and no
    file may have appeared, changed or gone since the guard prepared the folder
    or since the last run in it ended (file type, size, times and inode).
    """

    def __init__(self, path, label):
        self.path, self.label = path, label
        self.head, self.written, self.files = None, {}, {}

    def _walk(self):
        found = {}
        for folder, dirs, names in os.walk(self.path):
            for name in dirs + names:
                full = os.path.join(folder, name)
                rel = os.path.relpath(full, self.path).replace(os.sep, "/")
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    found[rel] = ("dir",)
                elif stat.S_ISLNK(st.st_mode):
                    found[rel] = ("link", os.readlink(full), st.st_mtime_ns, st.st_ctime_ns)
                else:
                    found[rel] = ("file", st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)
        return found

    def seal(self, head, written=()):
        """After the guard wrote and committed: remember the commit, the written files and the folder."""
        self.head = head
        self.written = {p: _file_digest(os.path.join(self.path, *p.split("/"))) for p in written}
        self.files = self._walk()

    def after_run(self):
        """After a run here: files the run itself left (caches, reports) are part of the state."""
        self.files = self._walk()

    def verify(self):
        problems = []
        now = self._walk()
        if now != self.files:
            problems += sorted(r for r in set(now) | set(self.files) if now.get(r) != self.files.get(r))
        problems += [p for p, digest in self.written.items()
                     if _file_digest(os.path.join(self.path, *p.split("/"))) != digest and p not in problems]
        out = git(self.path, "status", "--porcelain=v2", "--branch", "--untracked-files=no", "-z").stdout.decode("utf-8", "replace")
        oid = None
        for entry in out.split("\0"):
            if entry.startswith("# branch.oid "):
                oid = entry.split()[-1]
            elif entry and not entry.startswith("#"):
                path = entry.split(" ")[-1] if " " in entry else entry
                if path not in problems:
                    problems.append(path)
        # core.abbrev=40 gives the full name of a SHA-1 commit and 40 characters of a SHA-256 one.
        if not oid or not self.head or not (oid.startswith(self.head) or self.head.startswith(oid)):
            problems.append("HEAD")
        if problems:
            raise GuardStop(ERROR, "tampered", MESSAGES["tampered-worktree"].format(
                phase=self.label, files=list_files(problems, 4)), HINTS["tampered"])


def resolve(repo, rev, label):
    proc = git(repo, "rev-parse", "--verify", "--quiet", rev + "^{commit}", check=False)
    if proc.returncode != 0:
        raise GuardStop(ERROR, "git", "The %s commit %r is not in this clone, so the guard cannot judge this change; fetch the full history (fetch-depth 0)." % (label, rev))
    return proc.stdout.decode().strip()


def raw_changes(repo, base, head):
    """Return a list of (status, old_path, new_path) as git reports them, with rename detection."""
    out = git(repo, "diff", "--name-status", "-M", "--no-color", "-z", base, head).stdout.decode("utf-8", "replace")
    parts = out.split("\0")
    result = []
    i = 0
    while i < len(parts) and parts[i]:
        status = parts[i]
        if status[0] in ("R", "C"):
            result.append((status, parts[i + 1], parts[i + 2]))
            i += 3
        else:
            result.append((status, parts[i + 1], parts[i + 1]))
            i += 2
    return result


def changed_files(repo, base, head, raw=None):
    """Return a list of (status, path) for the change from base to head.

    Renames count as a change to the new path (status "R") and to the old
    path (status "D"); renamed_from() maps one to the other.
    """
    result = []
    for status, old, new in (raw if raw is not None else raw_changes(repo, base, head)):
        if status[0] == "R":
            result.append(("D", old))
            result.append(("R", new))
        elif status[0] == "C":
            result.append(("A", new))
        else:
            result.append((status[0], new))
    seen = {}
    for st, p in result:
        seen.setdefault(p, st)
    return [(st, path) for path, st in sorted(seen.items())]


def renamed_from(raw):
    """New path to old path, for every rename in the change."""
    return {new: old for status, old, new in raw if status[0] == "R"}


def show_file(repo, rev, path):
    proc = git(repo, "show", "%s:%s" % (rev, path), check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout


def tree_modes(repo, rev):
    """Every path of a commit with its git mode (100644, 100755, 120000 for a link, 160000 for a submodule).

    --full-tree lists the whole commit also when the guard runs in a subfolder
    of the checkout (version 0.3.2, RC-N3).
    """
    out = git(repo, "ls-tree", "-r", "--full-tree", "-z", rev).stdout.decode("utf-8", "replace")
    modes = {}
    for entry in out.split("\0"):
        meta, sep, path = entry.partition("\t")
        if sep and path:
            modes[path] = meta.split(" ")[0]
    return modes


def add_worktree(repo, sha, path):
    git(repo, "worktree", "add", "--detach", "--quiet", path, sha)


def remove_worktree(repo, path):
    git(repo, "worktree", "remove", "--force", path, check=False)
    shutil.rmtree(path, ignore_errors=True)


def diff_by_file(repo, base, head, paths):
    """Added and removed lines per file, from a zero-context diff."""
    files = {}
    if not paths:
        return files
    # Rename detection (-M) gives a renamed file only its real edits; core.quotepath=off
    # keeps non-ASCII paths readable. Pass both paths of a rename.
    # --text --no-textconv --no-ext-diff: a "-diff" line in .gitattributes cannot hide the lines (version 0.3.1, M5).
    out = git(repo, "-c", "core.quotepath=off", "diff", "-U0", "--no-color", "--text", "--no-textconv", "--no-ext-diff", "-M",
              base, head, "--", *paths).stdout.decode("utf-8", "replace")
    cur, minus, in_hunk = None, None, False
    for line in out.splitlines():
        if line.startswith("diff --git "):
            cur, minus, in_hunk = None, None, False
            continue
        if not in_hunk:
            if line.startswith("--- "):
                # git ends the name with a tab when it holds a space.
                minus = line[6:].rstrip("\t") if line.startswith("--- a/") else None
            elif line.startswith("+++ "):
                cur = line[6:].rstrip("\t") if line.startswith("+++ b/") else minus
                files.setdefault(cur, {"added": [], "removed": []})
            elif line.startswith("@@"):
                in_hunk = True
            continue
        if line.startswith("@@"):
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            files[cur]["added"].append(line[1:])
        elif line.startswith("-"):
            files[cur]["removed"].append(line[1:])
    return files


# --------------------------------------------------------------------------
# Running the tests
# --------------------------------------------------------------------------

class Budget:
    def __init__(self, seconds):
        self.seconds = seconds
        self.start = time.monotonic()

    def elapsed(self):
        return time.monotonic() - self.start

    def remaining(self, phase):
        left = self.seconds - self.elapsed()
        if left <= 0:
            raise BudgetExceeded(phase)
        return left


class SubBudget(Budget):
    """A budget that ends at its own limit or at the parent's, whichever comes first."""

    def __init__(self, seconds, parent):
        super().__init__(seconds)
        self.parent = parent

    def remaining(self, phase):
        parent_left = self.parent.remaining(phase)
        own_left = self.seconds - self.elapsed()
        if own_left <= 0:
            raise BudgetExceeded("probe-own")
        return min(parent_left, own_left)


def run_shell(command, cwd, budget, phase, env):
    popen_kwargs = {}
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    started = time.monotonic()
    remaining = budget.remaining(phase)
    # Output goes to a file, not a pipe: a child that outlives the test command
    # (a leaked helper or a daemon in its own session) cannot hold the guard open.
    with tempfile.TemporaryFile() as sink:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd, env=env,
            stdout=sink, stderr=subprocess.STDOUT, **popen_kwargs
        )
        # Wait for the process in a thread: Popen.wait(timeout) polls with growing
        # sleeps, which adds up to 50 ms to every run; an Event returns at once.
        exited = threading.Event()
        waiter = threading.Thread(target=lambda: (proc.wait(), exited.set()), daemon=True)
        waiter.start()
        try:
            if not exited.wait(remaining):
                _kill_tree(proc)
                budget.remaining(phase)      # raises the right phase (whole run or probe-own)
                raise BudgetExceeded(phase)
        finally:
            _kill_tree(proc)   # stop whatever the command left behind in its group
        sink.seek(0)
        out = sink.read()
    return proc.returncode, out.decode("utf-8", "replace"), time.monotonic() - started


def _kill_tree(proc):
    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    elif proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


PLACEHOLDER_RX = re.compile(r"\{(python|cg_tools|report|files|dirs|classes_csv|classes|gradle_tests|dotnet_filter|names_regex|functions)\}")


def fill_placeholders(template, values):
    """Fill every known placeholder in one pass, so a value can never be read as another placeholder."""
    return PLACEHOLDER_RX.sub(lambda m: values[m.group(1)] if m.group(1) in values else m.group(0), template)


def expand_command(template, files, report=""):
    """Fill the placeholders of a command with the changed test files.

    {files}         the test files, as paths from the repository root
    {dirs}          their folders, once each, as ./folder (for go test)
    {classes}       JVM class names from src/<set>/<java|kotlin|...>/ paths
    {gradle_tests}  the same class names, each as --tests <class>
    {classes_csv}   the same class names joined by commas (Maven's -Dtest=)
    {dotnet_filter} one dotnet test --filter expression that selects the
                    classes named like the test files (FullyQualifiedName~Name)
    {names_regex}   the file names without extension as one regular
                    expression (A|B), for swift test --filter
    {python}        the Python that runs the guard
    {report}        where the test command writes its per-test report
    {cg_tools}      the folder that holds change_guard.py (and cg_unittest_report.py)
    """
    dirs = []
    for f in files:
        d = os.path.dirname(f)
        d = "./" + d if d else "."
        if d not in dirs:
            dirs.append(d)
    classes = []
    for f in files:
        m = JVM_SOURCE_ROOT.search(f)
        if m and m.group(1).replace("/", ".") not in classes:
            classes.append(m.group(1).replace("/", "."))
    stems = []
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        if stem and stem not in stems:
            stems.append(stem)
    q = lambda items: " ".join(shlex.quote(x) for x in items)
    return fill_placeholders(template, {
        "python": shlex.quote(sys.executable),
        "cg_tools": shlex.quote(HERE),
        "report": shlex.quote(report) if report else "''",
        "files": q(files),
        "dirs": q(dirs),
        "classes": q(classes),
        "gradle_tests": " ".join("--tests " + shlex.quote(c) for c in classes),
        "classes_csv": shlex.quote(",".join(classes)) if classes else "''",
        "dotnet_filter": shlex.quote("|".join("FullyQualifiedName~" + s for s in stems)) if stems else "''",
        "names_regex": shlex.quote("|".join(re.escape(s) for s in stems)) if stems else "''",
    })


def command_environment(cfg, extra=None):
    """The environment for commands that run code from the change: plain variables only.

    SAFE_ENV and the names in pass_env (exact names, or patterns such as JAVA_*)
    pass through; NEVER_PASSED_ENV never does.
    """
    env = {}
    for name, value in os.environ.items():
        if name in NEVER_PASSED_ENV:
            continue
        if (name in SAFE_ENV or name.startswith(SAFE_ENV_PREFIXES)
                or any(fnmatch.fnmatchcase(name, pat) for pat in cfg["pass_env"])):
            env[name] = value
    env.update(extra or {})
    return env


def report_location(cfg, workdir, state, phase):
    if cfg["report_format"] == "none":
        return ""
    if cfg["report_path"]:
        return os.path.join(workdir, *cfg["report_path"].split("/"))
    # A random name of the same shape for every run (version 0.3.1, finding D2 of
    # the 0.3.0 audit): before, the head run always wrote run-1, so a test could
    # read the phase from its own report path. Since version 0.3.2 (the rest of M4,
    # RT-N2) every run also gets a new folder with a random name that holds nothing
    # else, and run_tests removes it once the report is read, so a test cannot
    # count the reports of earlier runs either. A test can still tell the runs apart
    # by looking at the code (README limits).
    folder = os.path.join(state["tmp_parent"], "reports", os.urandom(6).hex())
    os.makedirs(folder)
    return os.path.join(folder, "report-%s.%s" % (os.urandom(6).hex(), REPORT_FORMATS[cfg["report_format"]]))


def worktree_pythonpath(value, repo, workdir):
    """PYTHONPATH with every entry inside the main checkout moved to the same place in the worktree.

    Version 0.3.1 (finding I6 of the 0.3.0 audit): with a "src layout" the agent
    often sets PYTHONPATH to <checkout>/src, so the base run imported the head's
    code from the checkout and every honest change stopped as test-passes-on-base.
    An installed copy (pip install -e .) cannot be moved this way; README limits.
    """
    roots = sorted({os.path.abspath(repo), os.path.realpath(repo)}, key=len, reverse=True)
    out = []
    for entry in value.split(os.pathsep):
        moved = entry
        # The entry as written and as its real path (version 0.3.2, RT-N4): a path
        # that reaches the checkout through a symbolic link is moved as well.
        spellings = [os.path.abspath(entry), os.path.realpath(entry)] if entry else []
        for full in spellings:
            root = next((r for r in roots if full == r or full.startswith(r + os.sep)), None)
            if root is not None:
                moved = os.path.join(workdir, os.path.relpath(full, root)) if full != root else workdir
                break
        out.append(moved)
    return os.pathsep.join(out)


def run_tests(cfg, workdir, files, phase, budget, repo, state=None, do_setup=True):
    """Run the changed test files in one worktree.

    Returns a dict: rc, out, secs, records (a list of per-test records, or None
    when no report is configured or none was written) and report (its path).
    """
    state = state if state is not None else {"tmp_parent": tempfile.gettempdir()}
    report = report_location(cfg, workdir, state, phase)
    if report:
        if os.path.isdir(report):
            shutil.rmtree(report, ignore_errors=True)
        elif os.path.exists(report):
            os.remove(report)
    # The tests get the report path only. The phase and the main checkout are
    # given to the setup command, never to the tests, so a test cannot read
    # which commit it runs on (docs/how-it-works.md).
    env = command_environment(cfg, {"CHANGE_GUARD_REPORT": report})
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = worktree_pythonpath(env["PYTHONPATH"], repo, workdir)
    setup_env = dict(env, CHANGE_GUARD_PHASE=phase, CHANGE_GUARD_REPO=repo)
    command = expand_command(cfg["test_command"], files, report)
    log = []
    total = 0.0
    if cfg["setup_command"] and do_setup:
        setup = fill_placeholders(cfg["setup_command"], {"python": shlex.quote(sys.executable)})
        rc, out, secs = run_shell(setup, workdir, budget, phase, setup_env)
        total += secs
        log.append(out)
        if rc != 0:
            raise GuardStop(ERROR, "setup-failed",
                            "The setup command failed on the %s commit (exit %d), so the guard cannot run the tests there; if this is the base, the base may not build." % (phase, rc),
                            "Fix setup_command or the build of that commit, or use the documented skip step.")
    rc, out, secs = run_shell(command, workdir, budget, phase, env)
    total += secs
    log.append(out)
    if rc in (126, 127):
        raise GuardStop(ERROR, "command-not-found",
                        "The test command could not start on the %s commit (exit %d), so the guard cannot judge this change." % (phase, rc),
                        "Check test_command and that its tools are installed on this build agent.")
    records = None
    if report:
        records = relative_records(read_report(cfg["report_format"], report), workdir)
        # Read once, then gone, so the next run finds no trace of this one (version 0.3.2).
        gone = report if cfg["report_path"] else os.path.dirname(report)
        if os.path.isdir(gone) and not os.path.islink(gone):
            shutil.rmtree(gone, ignore_errors=True)
        elif os.path.lexists(gone):
            try:
                os.remove(gone)
            except OSError:
                pass
    if records is None and rc in cfg["inconclusive_exit_codes"]:
        raise GuardStop(ERROR, "inconclusive",
                        "The test command ended on the %s commit with exit %d, which the configuration marks as inconclusive, so the guard cannot judge this change." % (phase, rc),
                        "Look at the test output; exit codes such as pytest's 5 (no tests collected) mean the run proved nothing.")
    return {"rc": rc, "out": "".join(log), "secs": total, "records": records, "report": report}


def relative_records(records, workdir):
    """Test ids and groups with the worktree's own folder taken out (version 0.3.0).

    Jest and Vitest name each test file by its absolute path, PHPUnit writes it
    into the file attribute, and the head, base and probe worktrees live in
    different folders, so the same test would get a different id in each run
    and no base result would match its head result.
    """
    if not records:
        return records
    roots = sorted({workdir, os.path.realpath(workdir)}, key=len, reverse=True)

    def strip(value):
        for root in roots:
            for sep in ("/", "\\"):
                value = value.replace(root.rstrip("/\\") + sep, "")
        return value
    for r in records:
        r["id"] = strip(r["id"] or "")
        r["group"] = strip(r["group"] or "")
    return records


def tail(text, n, temp_root=None):
    """Last n lines of a test run, with the temporary folder shown as <temp>."""
    if temp_root:
        for root in sorted({temp_root, os.path.realpath(temp_root)}, key=len, reverse=True):
            text = text.replace(root, "<temp>")
    lines = text.rstrip().splitlines()
    # One very long line (a test that writes megabytes without a newline) is cut (version 0.3.1, D10).
    return [l if len(l) <= 2000 else l[:2000] + " [cut]" for l in lines[-n:]] if n > 0 else []


# --------------------------------------------------------------------------
# Per-test reports. Each parser returns a list of records:
#   {"id", "group", "outcome": passed|failed|error|skipped, "type", "message", "file_level"}
# or None when the report is missing or unreadable.
# --------------------------------------------------------------------------

def _rec(rid, group, outcome, etype="", message="", file_level=False):
    return {"id": rid, "group": group or "", "outcome": outcome, "type": etype or "",
            "message": message or "", "file_level": bool(file_level)}


def parse_unittest_json(text):
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out.append(_rec(r["id"], r.get("file"), r["outcome"], r.get("type"), r.get("message"), r.get("file_level")))
    return out


def parse_junit_xml(texts):
    """JUnit XML as written by pytest, Gradle, Maven Surefire, PHPUnit, Vitest and swift test."""
    out = []
    for text in texts:
        root = ElementTree.fromstring(text)
        for case in root.iter("testcase"):
            cls = case.get("classname") or ""
            name = case.get("name") or ""
            rid = cls + "." + name if cls else name
            group = case.get("file") or cls
            outcome, etype, message, file_level = "passed", "", "", False
            for child in case:
                tag = child.tag
                if tag in ("failure", "error"):
                    outcome = "failed" if tag == "failure" else "error"
                    etype = child.get("type") or ""
                    message = (child.get("message") or "") + "\n" + (child.text or "")
                    # pytest writes every exception in a test as a failure without a type.
                    m = re.match(r"([A-Za-z_][\w.]*(?:Error|Exception)):", child.get("message") or "")
                    pytest_assert = (child.get("message") or "").startswith("assert ") or (child.get("message") or "") == "assert" \
                        or (child.text or "").rstrip().endswith(": AssertionError")
                    if tag == "failure" and not etype and (pytest_assert or (m and ASSERTION_TYPE_RX.search(m.group(1)))):
                        # pytest writes an assertion failure without a type, and for a plain
                        # "assert a == b" without the word AssertionError in the message: keep the
                        # class, so the word lists never read the test's own text (version 0.3.1,
                        # finding I4; version 0.3.2, RC-N4).
                        etype = "AssertionError" if pytest_assert and not (m and ASSERTION_TYPE_RX.search(m.group(1))) else m.group(1)
                    elif tag == "failure" and not etype and m:
                        outcome, etype = "error", m.group(1)
                    break
                if tag == "skipped":
                    outcome, etype, message = "skipped", "skip", child.get("message") or ""
            if outcome == "error" and not cls:
                # pytest reports a module that fails to collect as a test case
                # with an empty class name and the module as its name.
                file_level, group = True, name
            out.append(_rec(rid, group, outcome, etype, message.strip(), file_level))
    return out


def parse_go_json(text):
    """Events from go test -json. A package that does not build is one file-level error."""
    out, outputs, results = [], {}, {}
    build_output = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        ev = json.loads(line)
        action, pkg, test = ev.get("Action"), ev.get("Package") or ev.get("ImportPath") or "", ev.get("Test")
        if action == "output" or action == "build-output":
            if action == "build-output":
                build_output.append(ev.get("Output", ""))
            outputs.setdefault((pkg, test), []).append(ev.get("Output", ""))
        elif action in ("pass", "fail", "skip"):
            if test:
                results[(pkg, test)] = action
            elif action == "fail":
                text_out = "".join(outputs.get((pkg, None), []) + build_output)
                if ev.get("FailedBuild") or "[build failed]" in text_out or "[setup failed]" in text_out:
                    out.append(_rec("build:" + pkg, pkg, "error", "build-failed", text_out.strip(), True))
    for (pkg, test), action in results.items():
        outcome = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
        message = "".join(outputs.get((pkg, test), []))
        etype = "panic" if "panic:" in message else ""
        out.append(_rec(pkg + "/" + test, pkg, "error" if etype else outcome, etype, message.strip()))
    return out


def parse_jest_json(text):
    """Jest --json, and Vitest --reporter=json (Jest-compatible fields)."""
    data = json.loads(text)
    out = []
    for suite in data.get("testResults", []):
        group = suite.get("name") or suite.get("testFilePath") or ""
        assertions = suite.get("assertionResults") or suite.get("testResults") or []
        exec_error = suite.get("testExecError")
        if exec_error or (suite.get("status") == "failed" and not assertions):
            msg = exec_error.get("message", "") if isinstance(exec_error, dict) else (suite.get("message") or "")
            out.append(_rec("load:" + group, group, "error", "load", msg, True))
        for a in assertions:
            status = a.get("status")
            outcome = {"passed": "passed", "failed": "failed"}.get(status, "skipped")
            name = a.get("fullName") or " ".join((a.get("ancestorTitles") or []) + [a.get("title", "")])
            message = "\n".join(a.get("failureMessages") or [])
            etype = js_error_type(message) if outcome == "failed" else ""
            out.append(_rec(group + "::" + name, group, outcome, etype, message))
    return out


JS_ERROR_RX = re.compile(r"^\s*((?:[A-Za-z_$][\w$.]*)?(?:Error|Exception))(?::|\s|$)")


def js_error_type(message):
    """The error class at the start of a Jest or Vitest failure message (version 0.3.0).

    Vitest names its assertion errors (AssertionError: expected 10000 to be
    9000); Jest prints its matcher failures as a plain Error whose text starts
    with expect(, which counts as an assertion too. Any other class (TypeError,
    RangeError, a plain Error from the code) is an exception, not an assertion.
    """
    first = next((line for line in message.splitlines() if line.strip()), "")
    m = JS_ERROR_RX.match(first)
    if not m:
        return ""
    if m.group(1) == "Error" and re.match(r"\s*Error:\s*(?:\x1b\[[0-9;]*m)*expect", first):
        return "JestAssertionError"
    return m.group(1)


def parse_rspec_json(text):
    data = json.loads(text)
    out = []
    for ex in data.get("examples", []):
        status = ex.get("status")
        exc = ex.get("exception") or {}
        etype = exc.get("class", "")
        outcome = {"passed": "passed", "pending": "skipped"}.get(status, "failed")
        if outcome == "failed" and etype and not ASSERTION_TYPE_RX.search(etype):
            outcome = "error"
        out.append(_rec(ex.get("id") or ex.get("full_description"), ex.get("file_path"), outcome, etype, exc.get("message", "")))
    summary = data.get("summary") or {}
    if summary.get("errors_outside_of_examples_count"):
        out.append(_rec("load:outside-examples", "", "error", "load", "\n".join(data.get("messages") or []), True))
    return out


TRX_NS = "{http://microsoft.com/schemas/VisualStudio/TeamTest/2010}"
TRX_EXCEPTION_RX = re.compile(r"^\s*((?:[A-Za-z_][\w.]*)?(?:Exception|Error))\s*:")


def parse_trx(texts):
    """The TRX files that dotnet test writes with --logger trx (version 0.3.0).

    One record per UnitTestResult, with the test class as its group. An
    exception that is not an assertion (xUnit, NUnit and MSTest start such a
    message with the exception's class) is an error; any other failure counts
    as an assertion failure, as with JUnit XML.
    """
    out = []
    for text in texts:
        root = ElementTree.fromstring(text)
        ns = TRX_NS if root.tag.startswith(TRX_NS) else ""
        classes = {}
        for unit in root.iter(ns + "UnitTest"):
            method = unit.find(ns + "TestMethod")
            if method is not None:
                classes[unit.get("id")] = (method.get("className") or "", method.get("name") or "")
        for result in root.iter(ns + "UnitTestResult"):
            cls, method = classes.get(result.get("testId"), ("", ""))
            name = result.get("testName") or method
            rid = name if (not cls or name.startswith(cls + ".")) else cls + "." + name
            status = (result.get("outcome") or "").lower()
            message = ""
            info = result.find(ns + "Output/" + ns + "ErrorInfo")
            if info is not None:
                message = "\n".join(x.text or "" for x in (info.find(ns + "Message"), info.find(ns + "StackTrace")) if x is not None)
            if status == "passed":
                outcome, etype = "passed", ""
            elif status in ("failed", "error", "timeout", "aborted"):
                m = TRX_EXCEPTION_RX.match(message)
                if m and not ASSERTION_TYPE_RX.search(m.group(1)) and not m.group(1).startswith("Xunit.Sdk."):
                    outcome, etype = "error", m.group(1)
                else:
                    outcome, etype = "failed", ""
            else:
                outcome, etype = "skipped", status or "skip"
            out.append(_rec(rid, cls, outcome, etype, message.strip()))
    return out


def read_report(fmt, path):
    try:
        if os.path.isdir(path):
            # A folder of report files (Maven Surefire, Gradle, dotnet test --results-directory).
            suffix = ".trx" if fmt == "dotnet-trx" else ".xml"
            texts = []
            for folder, _, names in os.walk(path):
                for name in sorted(names):
                    if name.endswith(suffix):
                        with open(os.path.join(folder, name), encoding="utf-8-sig", errors="replace") as fh:
                            texts.append(fh.read())
            if not texts:
                return None
            return parse_trx(texts) if fmt == "dotnet-trx" else parse_junit_xml(texts)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if fmt == "unittest-json":
            return parse_unittest_json(text)
        if fmt == "junit-xml":
            return parse_junit_xml([text])
        if fmt == "go-json":
            return parse_go_json(text)
        if fmt == "jest-json":
            return parse_jest_json(text)
        if fmt == "rspec-json":
            return parse_rspec_json(text)
        if fmt == "dotnet-trx":
            return parse_trx([text.lstrip("\ufeff")])
    except (ValueError, KeyError, TypeError, ElementTree.ParseError):
        return None
    return None


# --------------------------------------------------------------------------
# Symbols the change adds
# --------------------------------------------------------------------------

def python_definitions(source):
    """Functions, class names and top-level names of a Python file.

    Returns (funcs, names). funcs maps a qualified name ("f", "Cart.add") to the
    list of its definitions: def and async def statements, also inside if, try,
    with, for, while and match blocks, and lambdas assigned to a name. A name
    defined twice (for example in both branches of an if) has two entries.
    """
    tree = ast.parse(source)
    funcs, names = {}, set()

    def visit(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.setdefault(prefix + node.name, []).append(node)
                names.add(node.name)
                if prefix:
                    # Attributes a method sets on self are names of the class (version 0.3.1, finding I2).
                    for sub in ast.walk(node):
                        for target in getattr(sub, "targets", None) or ([sub.target] if isinstance(sub, (ast.AnnAssign, ast.AugAssign)) else []):
                            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                                    and target.value.id == "self"):
                                names.add(target.attr)
            elif isinstance(node, ast.ClassDef):
                names.add(node.name)
                visit(node.body, prefix + node.name + ".")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        # Module names and, since 0.3.1, class attributes.
                        names.add(target.id)
                        if isinstance(node.value, ast.Lambda):
                            funcs.setdefault(prefix + target.id, []).append(node.value)
                            names.add(target.id)
            else:
                # Compound statements: a function defined inside them is still a function.
                for field in ("body", "orelse", "finalbody"):
                    inner = getattr(node, field, None)
                    if isinstance(inner, list):
                        visit(inner, prefix)
                for handler in getattr(node, "handlers", None) or []:
                    visit(handler.body, prefix)
                for case in getattr(node, "cases", None) or []:
                    visit(case.body, prefix)
    visit(tree.body, "")
    return funcs, names


def _raises_not_implemented(stmt):
    if not isinstance(stmt, ast.Raise) or stmt.exc is None:
        return False
    exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
    return getattr(exc, "id", None) == "NotImplementedError" or getattr(exc, "attr", None) == "NotImplementedError"


def is_stub(node):
    """True for a definition whose body cannot carry behaviour a test could notice.

    Bodies that are only a docstring, pass, ... or raise NotImplementedError,
    as abstract methods and typing overloads have. The probe leaves them alone.
    The body decides, never a decorator alone: abc.abstractmethod on a module
    function, or a home-made decorator of that name, leaves the function as
    callable as before, so a real body under it is probed.
    """
    if isinstance(node, ast.Lambda):
        return False
    body = [stmt for stmt in node.body if not _is_docstring(stmt)]
    if not body:
        return True
    if len(body) != 1:
        return False
    stmt = body[0]
    return (isinstance(stmt, ast.Pass)
            or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis)
            or _raises_not_implemented(stmt))


def _parameter_names(node):
    a = node.args
    names = [x.arg for x in getattr(a, "posonlyargs", []) + a.args + a.kwonlyargs]
    names += [x.arg for x in (a.vararg, a.kwarg) if x is not None]
    return set(names)


def python_module_name(path):
    p = path[:-3] if path.endswith(".py") else path
    if p.endswith("/__init__"):
        p = p[:-len("/__init__")]
    return p.replace("/", ".")


def _body_dump(node):
    """A function's code without its docstring, to see whether a change edited it."""
    body = [stmt for stmt in getattr(node, "body", []) if not _is_docstring(stmt)] if not isinstance(node, ast.Lambda) else [node.body]
    return ast.dump(ast.Module(body=body, type_ignores=[])) + ast.dump(node.args)


def _literal_names(node):
    """The strings of a list or tuple of string constants (an __all__), or None."""
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None
    return set(value) if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value) else None


def _scope_statements(tree):
    """The statements of the module and of each class body that are not a def, a class or a docstring.

    Returns {scope: [(dump, label, node)]} with scope "" for the module and
    "Cart." for a class, and the class headers {qualified name: dump}.
    """
    scopes, headers = {}, {}

    def visit(body, prefix):
        items = scopes.setdefault(prefix, [])
        for i, node in enumerate(body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(node, ast.ClassDef):
                headers[prefix + node.name] = "".join(ast.dump(x) for x in node.bases + node.keywords + node.decorator_list)
                visit(node.body, prefix + node.name + ".")
                continue
            if (i == 0 and _is_docstring(node)) or isinstance(node, ast.Pass) or (
                    isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
                # A docstring, pass or ... carries no behaviour.
                continue
            targets = node.targets if isinstance(node, ast.Assign) else (
                [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else [])
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if names:
                label = ", ".join(prefix + n for n in names)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                label = "import"
            else:
                label = ("code in the body of class %s" % prefix[:-1]) if prefix else "module-level code"
            dump = ast.dump(node)
            if isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
                # A type hint added to or changed on a value is not an edit of it (version 0.3.3, C-N3).
                dump = ast.dump(ast.Assign(targets=[node.target], value=node.value, type_comment=None))
            items.append((dump, label, node))
    visit(tree.body, "")
    return scopes, headers


def _imports(items):
    """(level, module, name, bound name) for every import statement among the items."""
    out = set()
    for _, label, node in items:
        if isinstance(node, ast.Import):
            out.update((0, None, a.name, a.asname or a.name.split(".")[0]) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.update((node.level, node.module, a.name, a.asname or a.name) for a in node.names)
    return out


def python_edits(base_tree, head_tree, base_funcs, head_funcs):
    """Edits of existing Python code that no function body shows (version 0.3.2, the rest of D1).

    A changed or removed statement of the module or of a class body (a class
    attribute, a module-level call, a value), a changed class header, a changed
    or replaced decorator, and a deleted function or class. Added statements,
    new functions, docstrings and comments do not count; an import that only
    gains names does not count either, and neither does an __all__ that only
    gains names. Returns labels for the reviewer, in order.
    """
    labels = []
    base_scopes, base_headers = _scope_statements(base_tree)
    head_scopes, head_headers = _scope_statements(head_tree)
    for q in base_funcs:
        if q not in head_funcs:
            labels.append("%s (deleted)" % q)
        else:
            old, new = base_funcs[q][-1], head_funcs[q][-1]
            old_deco = type(old).__name__ + "".join(ast.dump(d) for d in getattr(old, "decorator_list", []))
            new_deco = type(new).__name__ + "".join(ast.dump(d) for d in getattr(new, "decorator_list", []))
            if old_deco != new_deco:
                labels.append("the decorators of %s" % q)
    for q, header in base_headers.items():
        if q not in head_headers:
            labels.append("class %s (deleted)" % q)
        elif head_headers[q] != header:
            labels.append("the header of class %s" % q)
    for scope, items in base_scopes.items():
        if scope and scope[:-1] not in head_headers:
            continue
        head_items = head_scopes.get(scope, [])
        left = {}
        for dump, _, _ in head_items:
            left[dump] = left.get(dump, 0) + 1
        head_imports = _imports(head_items)
        head_bound = {t[3] for t in head_imports}
        for dump, label, node in items:
            if left.get(dump):
                left[dump] -= 1
                continue
            if label == "import":
                # Only an import that now binds a name from somewhere else is an edit.
                if any(t not in head_imports and t[3] in head_bound for t in _imports([(dump, label, node)])):
                    labels.append("an import in %s" % ("class %s" % scope[:-1] if scope else "the module"))
                continue
            if label == scope + "__all__" and isinstance(node, (ast.Assign, ast.AnnAssign)):
                old_names = _literal_names(node.value)
                new_all = [n for _, l, n in head_items if l == label and isinstance(n, (ast.Assign, ast.AnnAssign))]
                new_names = _literal_names(new_all[-1].value) if new_all else None
                if old_names is not None and new_names is not None and old_names <= new_names:
                    continue
            labels.append(label)
        # A new statement that assigns to a name the base already has in this scope
        # changes its value (version 0.3.3, C-N3); reordered statements are not seen.
        bound = set(base_funcs) | set(base_headers) | {scope + n for _, _, b in items for n in _assigned(b)}
        in_base = {}
        for dump, _, _ in items:
            in_base[dump] = in_base.get(dump, 0) + 1
        for dump, label, node in head_items:
            if in_base.get(dump):
                in_base[dump] -= 1
                continue
            labels.extend(scope + n for n in _assigned(node) if n != "__all__" and scope + n in bound)
    return list(dict.fromkeys(labels))


def _assigned(node):
    """The plain names an assignment statement binds."""
    targets = node.targets if isinstance(node, ast.Assign) else (
        [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else [])
    return [t.id for t in targets if isinstance(t, ast.Name)]


def added_symbols(repo, base, head, protected_changes, diff, renames=None, modified=None, owners=None):
    """Names the change adds in protected files, and the Python functions to probe per file.

    protected_changes: list of (status, path) for protected files that exist on the head.
    renames: new path to old path for renamed files; a renamed file is compared
    with its old path on the base, so only its real edits count as added.
    Returns (names, python_functions) where python_functions maps a file to the
    qualified names of functions that are new on the head, or whose signature
    gained a parameter. Stubs (is_stub) are left out of python_functions.

    modified, when a list is given, receives the existing code the change edits
    (version 0.3.1, finding D1 of the 0.3.0 audit): Python functions whose code
    changed without gaining a parameter, top-level names whose value changed,
    and, for other languages, the files where the change removed or replaced
    lines. A probe of the new functions shows nothing about that code.
    """
    renames = renames or {}
    names, py_functions = set(), {}
    for status, path in protected_changes:
        for line in diff.get(path, {}).get("added", []):
            for rx in DEFINITION_PATTERNS:
                m = rx.match(line)
                if m and m.group(1) not in DEFINITION_KEYWORDS:
                    names.add(m.group(1))
        if not path.endswith(".py"):
            if modified is not None and status != "A" and [l for l in diff.get(path, {}).get("removed", []) if l.strip()]:
                modified.append(path)
            continue
        head_src = show_file(repo, head, path)
        if head_src is None:
            continue
        base_path = renames.get(path, path)
        base_src = show_file(repo, base, base_path) if status != "A" else None
        try:
            head_funcs, head_names = python_definitions(head_src)
        except (SyntaxError, ValueError):
            continue
        base_funcs, base_names = {}, set()
        if base_src is not None:
            try:
                base_funcs, base_names = python_definitions(base_src)
            except (SyntaxError, ValueError):
                pass
        new_funcs = [q for q in head_funcs if q not in base_funcs]
        names.update(n for n in head_names if n not in base_names)
        names.update(q.split(".")[-1] for q in new_funcs)
        # A new parameter is new code too: its name, and the function it belongs to,
        # which the probe then covers. A renamed parameter (as many added as removed)
        # only adds the name, so a refactor is not probed for it.
        widened = []
        for q in head_funcs:
            if q in base_funcs:
                old_params = _parameter_names(base_funcs[q][-1])
                new_params = _parameter_names(head_funcs[q][-1])
                names.update(new_params - old_params)
                if owners is not None:
                    for param in new_params - old_params:
                        owners.setdefault(param, set()).add(q)
                if len(new_params - old_params) > len(old_params - new_params):
                    names.add(q.split(".")[-1])
                    widened.append(q)
        if modified is not None and base_src is not None:
            for q in head_funcs:
                if q in base_funcs and q not in widened and _body_dump(head_funcs[q][-1]) != _body_dump(base_funcs[q][-1]):
                    modified.append(q)
            try:
                for label in python_edits(ast.parse(base_src), ast.parse(head_src), base_funcs, head_funcs):
                    if label not in modified:
                        modified.append(label)
            except (SyntaxError, ValueError):
                pass
        targets = [q for q in new_funcs + widened if not all(is_stub(n) for n in head_funcs[q])]
        if targets:
            py_functions[path] = targets
        if status == "A":
            module = python_module_name(path)
            names.add(module)
            names.add(module.split(".")[-1])
    return names, py_functions


# --------------------------------------------------------------------------
# Classification of each changed test's result on the base
# --------------------------------------------------------------------------

PROOF_CLASSES = ("failed-assertion",)
NEW_CODE_CLASSES = ("errored-new-symbol", "errored-missing-file", "errored-unknown-name")


def missing_symbol_name(text, added, patterns):
    """The first name in an error message that a missing-symbol pattern captures and the change adds."""
    for rx in patterns:
        for m in rx.finditer(text):
            name = m.group(1)
            if name in added or name.split(".")[-1] in added or name.split("/")[-1] in added:
                return name
    return None


def names_added_path(text, added_paths):
    if not any(h in text for h in FILE_ERROR_HINTS):
        return None
    for p in added_paths:
        base = p.split("/")[-1]
        if p in text or (len(base) > 4 and base != "__init__.py" and base in text):
            return p
    return None


CONTROL_RX = re.compile("[\x00-\x08\x0a-\x1f\x7f\x85\u2028\u2029]")


def one_line(text):
    """Text from the change with every character that can end or redraw a line shown as \\xNN or \\uNNNN.

    Version 0.3.1 (M6) used this for the printed lines; since 0.3.2 (RC-N6) the
    annotation line and the step summary use it too, so a carriage return in a
    file name cannot start a line of its own there either.
    """
    return CONTROL_RX.sub(lambda m: ("\\x%02x" if ord(m.group(0)) < 0x100 else "\\u%04x") % ord(m.group(0)), text)


MARKDOWN_SPECIAL_RX = re.compile(r"([\\`*_{}\[\]()#+\-.!|~:])")


def markdown_text(text):
    """Text from the change for the Markdown step summary, shown as text (version 0.3.2, RC-N6).

    One line, Markdown punctuation escaped with a backslash and the HTML
    characters as entities, so a heading, a table, a link or a tag written by
    the change is shown as the characters it is.
    """
    text = MARKDOWN_SPECIAL_RX.sub(r"\\\1", one_line(text))
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
ANSI_RX = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def missing_symbol_line(rec, ctx):
    """The line of an error that names a missing symbol the change adds, for the reviewer (version 0.3.0).

    A compiler run that wrote no report (javac through Maven, the C# compiler
    through dotnet test) starts its output with progress lines, so the first
    line of the text says nothing about the cause.
    """
    text = rec.get("message") or ""
    for rx in ctx["missing_rx"]:
        for m in rx.finditer(text):
            name = m.group(1)
            if name in ctx["added"] or name.split(".")[-1] in ctx["added"] or name.split("/")[-1] in ctx["added"]:
                start = text.rfind("\n", 0, m.start()) + 1
                end = text.find("\n", m.end())
                # A javac message spans two lines (cannot find symbol / symbol: method name): one line here.
                # The Swift compiler colours its messages even without a terminal.
                line = ANSI_RX.sub("", text[start:end if end >= 0 else len(text)])
                return " ".join(line.split())[:220]
    return None


NONE_ATTRIBUTE_RX = re.compile(r"'NoneType' object has no attribute")


def unknown_missing_name(text, patterns):
    """A name that a missing-symbol pattern captures, whether or not the change adds it."""
    if NONE_ATTRIBUTE_RX.search(text):
        # A function that returned None where an object was due is behaviour, not a missing name.
        return None
    for rx in patterns:
        m = rx.search(text)
        if m:
            return m.group(1)
    return None


def classify_error(rec, ctx, fallback, file_level=False):
    """The class of one error on the base.

    Version 0.3.1 (findings I2 and I4 of the 0.3.0 audit): the environment words
    ("timed out", "FileNotFoundError" ...) apply only to a load error or to output
    without a report, never to an exception raised inside a test, where they are
    the behaviour under test; and an exception inside a test that names a missing
    name the guard cannot link to the change (a dictionary key, an attribute) is
    "errored-unknown-name": never proof, at most ok-unproven.
    """
    text = (rec.get("type") or "") + ": " + (rec.get("message") or "")
    name = missing_symbol_name(text, ctx["added"], ctx["missing_rx"])
    ctx["_last_name"] = name
    if name:
        return "errored-new-symbol"
    missing = names_added_path(text, ctx["added_paths"])
    if missing:
        # The file is what no probe covers (version 0.3.2): the verdict names it, not the class.
        ctx["_last_name"] = missing
        return "errored-missing-file"
    if file_level or rec.get("file_level"):
        if any(p and p in text for p in ctx["env_patterns"]):
            return "errored-environment"
        return fallback
    unknown = unknown_missing_name(text, ctx["missing_rx"])
    if unknown:
        ctx["_last_name"] = unknown
        return "errored-unknown-name"
    return fallback


def _norm_group(value):
    v = (value or "").replace("\\", "/").strip()
    if v.startswith("./"):
        v = v[2:]
    v = re.sub(r"\.(py|js|jsx|ts|tsx|mjs|cjs|go|rb|php|java|kt|swift|cs)$", "", v)
    return v.strip("/").replace("/", ".")


def find_file_error(test, file_errors):
    tg, tid = _norm_group(test.get("group")), _norm_group(test.get("id"))
    for err in file_errors:
        g = _norm_group(err.get("group"))
        if g and (tg == g or tg.startswith(g + ".") or tid.startswith(g + ".")):
            return err
    if len(file_errors) == 1 and not _norm_group(file_errors[0].get("group")):
        return file_errors[0]
    return None


def classify_base(head_passed, base_records, ctx):
    """One class per test that passed on the head, from its record on the base."""
    base_by_id = {r["id"]: r for r in base_records if not r["file_level"]}
    file_errors = [r for r in base_records if r["file_level"]]
    classes = {}
    # The missing name behind each "new code" class, for the verdict (version 0.3.1).
    matched = ctx.setdefault("matched", {})
    for t in head_passed:
        b = base_by_id.get(t["id"])
        if b is None:
            err = find_file_error(t, file_errors)
            if err is None:
                classes[t["id"]] = ("not-collected", "")
            else:
                cls = classify_error(err, ctx, "errored-load", file_level=True)
                matched[t["id"]] = ctx.get("_last_name")
                detail = (missing_symbol_line(err, ctx) if cls == "errored-new-symbol" else None) or first_line(err)
                classes[t["id"]] = (cls, detail)
            continue
        if b["outcome"] == "passed":
            classes[t["id"]] = ("passed", "")
        elif b["outcome"] == "skipped":
            classes[t["id"]] = ("skipped", b.get("type", ""))
        elif b["outcome"] == "failed":
            if ASSERTION_TYPE_RX.search(b.get("type") or "") and ctx.get("trust_assertion_type", True):
                classes[t["id"]] = ("failed-assertion", first_line(b))
            else:
                # A failure whose type names an exception that is not an assertion
                # (a TypeError in a Jest or Vitest test) is an error (version 0.3.0).
                fallback = "errored-other" if JS_ERROR_RX.match(b.get("type") or "") else "failed-assertion"
                classes[t["id"]] = (classify_error(b, ctx, fallback), first_line(b))
                matched[t["id"]] = ctx.get("_last_name")
        else:
            classes[t["id"]] = (classify_error(b, ctx, "errored-other"), first_line(b))
            matched[t["id"]] = ctx.get("_last_name")
    return classes


def first_line(rec):
    text = (rec.get("message") or rec.get("type") or "").strip()
    lines = [re.sub(r"^E\s{2,}", "", l.strip()) for l in text.splitlines() if l.strip()]
    if not lines:
        return rec.get("type") or ""
    # Prefer the line that names the exception (Python puts it last); otherwise the first.
    named = [l for l in lines if EXCEPTION_LINE_RX.match(l)]
    line = named[-1] if named else lines[0]
    return line[:220]


EXCEPTION_LINE_RX = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Failure|Exit|Interrupt)\b")


def split_classes(classes, cfg):
    """P (proof), N (new code missing on the base) and E (no evidence) as lists of test ids."""
    proof = [t for t, (c, _) in classes.items() if c in PROOF_CLASSES or (c == "errored-other" and cfg["errored_counts_as_proof"])]
    new = [t for t, (c, _) in classes.items() if c in NEW_CODE_CLASSES]
    other = [t for t, (c, _) in classes.items() if c not in ("passed", "skipped") and t not in proof and t not in new]
    return proof, new, other


def first_decision(classes, cfg):
    """The stops that need no probe and no second base run, or None to continue."""
    if all(c in ("passed", "skipped") for c, _ in classes.values()):
        return GuardStop(STOPPED, "test-passes-on-base", MESSAGES["test-passes-on-base"], HINTS["test-passes-on-base"])
    proof, new, other = split_classes(classes, cfg)
    if other and not proof and not new:
        first = next((detail for t, (c, detail) in classes.items() if t in other and detail), "")
        if not first:
            first = next(c for t, (c, _) in classes.items() if t in other)
        return GuardStop(ERROR, "base-error-unrelated", MESSAGES["base-error-unrelated"].format(first=first), HINTS["base-error-unrelated"])
    return None


def final_decision(proof, new, probe_state, cfg, has_report=True, only_errored_proof=False, unproven=()):
    """The verdict once the base runs agree and the probe (if any) has covered every added function.

    probe_state: "covered" when the probe ran and every added function was noticed,
    "none" when no probe ran (no added function, probe off or unavailable).
    """
    if proof:
        if not has_report:
            return GuardStop(PASSED, "ok", MESSAGES["ok-exit-code"])
        return GuardStop(PASSED, "ok", MESSAGES["ok-errored"] if only_errored_proof else MESSAGES["ok"])
    if new:
        if unproven and probe_state == "covered":
            # Version 0.3.1: the probe covered the new functions, but not everything the tests rest on.
            what = " and ".join(unproven)
            if cfg["base_error_policy"] == "stop":
                return GuardStop(STOPPED, "base-error-only", MESSAGES["base-error-only-partial"].format(what=what), HINTS["base-error-only"])
            return GuardStop(PASSED, "ok-unproven", MESSAGES["ok-unproven-partial"].format(what=what))
        if probe_state == "covered":
            return GuardStop(PASSED, "ok-new-code", MESSAGES["ok-new-code"])
        if cfg["base_error_policy"] == "stop":
            return GuardStop(STOPPED, "base-error-only", MESSAGES["base-error-only"], HINTS["base-error-only"])
        return GuardStop(PASSED, "ok-unproven", MESSAGES["ok-unproven"])
    return GuardStop(ERROR, "internal", "The guard reached a verdict without proof or new code, which is a bug in the guard.")


MESSAGES = {
    "ok-exit-code": "The new or changed test files fail on the base commit and pass on the head commit, so they show the change in behaviour.",
    "ok": "The new or changed tests fail on the base commit by assertion and pass on the head commit, so they show the change in behaviour.",
    "ok-errored": "The new or changed tests raise an exception on the base commit that no missing name explains and pass on the head commit, so they show the change in behaviour.",
    "ok-new-code": "The new tests could not run on the base because the code they call is new in this change, and they fail when that new code is replaced by an empty body, so they depend on what the change adds.",
    "ok-unproven": "The new tests fail on the base only because the code they call is new in this change, and no probe ran, so the guard cannot show that they check its behaviour; a reviewer should read the assertions.",
    "ok-unproven-partial": "The new tests fail on the base only because code this change adds is missing there, and the probe covered the new functions but not {what}, so the guard cannot show that the tests check all of this change; a reviewer should read the assertions and that code.",
    "base-error-only-partial": "The new tests fail on the base only because code this change adds is missing there, and the probe covered the new functions but not {what}, which shows nothing about that part, so the change is stopped (base_error_policy stop).",
    "base-error-only": "The new tests fail on the base only because the code they call does not exist there yet, which shows nothing about behaviour, and the probe is off or not available for this language.",
    "probe-passes": "The new tests still pass when the body of {functions} is replaced by an empty return, so they would not notice that code being wrong.",
    "probe-broken": "The guard could not replace the body of {functions} without breaking the file, so it could not run the probe.",
    "probe-time-budget": "The probe ran past its own time budget of {seconds:.0f} seconds while testing {functions}, so the guard could not show that the new tests depend on that code.",
    "base-error-unrelated": "The new tests cannot run on the base commit for a reason the guard cannot link to a name or file this change adds ({first}), so the guard cannot judge this change.",
    "flaky-on-base": "The new tests gave different results in two runs on the base commit, so they cannot show what this change does; make them stable first.",
    "no-test-collected": "The changed test files ran on the head commit but the runner found no tests in them, so nothing was tested.",
    "no-test-ran": "Every test in the changed test files was skipped or marked as an expected failure on the head commit, so nothing was tested.",
    "whitespace-only": "The protected Python files changed only in whitespace or blank lines and parse to the same syntax tree, so the guard passed this change without running any test.",
    "pure-rename": "The protected files were only renamed, with identical content, so the guard passed this change without running any test.",
    "generated": "Every changed protected file carries a generated-code marker, so the guard passed this change without running any test.",
    "test-passes-on-base": "The new or changed test files also pass on the base commit without this change, so they would not catch the change being wrong.",
    "report-missing": "The test command finished on the head commit but wrote no readable {fmt} report, so the guard cannot read the per-test results it is configured for.",
    "edited-test-would-fail": "The version of {files} before this change fails on the head commit, so the edit to that test may hide a behaviour this change broke.",
    "tampered": "The test run changed {files}, which belong to the guard, the repository's git setup or the CI platform, so the guard cannot trust this run; what the tests changed in the repository's .git was put back, and text they added to the other files was removed where it could be.",
    "tampered-worktree": "The worktree the guard prepared for the {phase} run changed after the guard prepared it ({files}), so the guard cannot trust this run.",
}

HINTS = {
    "test-passes-on-base": "Add an assertion on the behaviour this change introduces, so the test fails on the base.",
    "base-error-unrelated": "Make the base commit build and load the test files (or overlay what is missing), or use the documented skip step.",
    "base-error-only": "Ask a reviewer to read the assertions and record a skip with the reason, or turn on a probe for this language.",
    "probe-passes": "Assert on the result or the effect of the new code, so the test fails when that code is wrong.",
    "probe-broken": "Check the new function for code the probe cannot rewrite, or use the documented skip step.",
    "probe-time-budget": "Raise probe_time_budget_seconds, narrow test_command, or use the documented skip step.",
    "flaky-on-base": "Remove the dependence on time, order, randomness or the environment from the new tests.",
    "no-test-collected": "Check that the test files hold tests the runner collects (names, classes, patterns).",
    "no-test-ran": "Remove the skip or expected-failure marker from at least one test of the change.",
    "report-missing": "Check that test_command writes the report to {report}, or set report_path.",
    "edited-test-would-fail": "Read the edit to that test with the change: if the behaviour changed on purpose, say so in the review.",
    "tampered": "Read the tests of this change for code that writes outside its own worktree before anything else is done with it.",
}


# --------------------------------------------------------------------------
# The neutral-body probe for Python
# --------------------------------------------------------------------------

def _is_docstring(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(getattr(stmt, "value", None), ast.Constant)
            and isinstance(stmt.value.value, str))


def _char_offsets(lines):
    """Start offset of every line in the joined source."""
    starts, pos = [], 0
    for line in lines:
        starts.append(pos)
        pos += len(line)
    starts.append(pos)
    return starts


def _position(lines, starts, lineno, col_bytes):
    """Offset in the joined source of an ast position (ast columns count UTF-8 bytes)."""
    line = lines[lineno - 1]
    return starts[lineno - 1] + len(line.encode("utf-8")[:col_bytes].decode("utf-8", "replace"))


def _is_neutral(node):
    if isinstance(node, ast.Lambda):
        return isinstance(node.body, ast.Constant) and node.body.value is None
    body = [s for s in node.body if not _is_docstring(s)]
    return (len(body) == 1 and isinstance(body[0], ast.Return)
            and isinstance(body[0].value, ast.Constant) and body[0].value.value is None)


def neutralise_python(source, qualnames):
    """Replace the body of each named function with "return None", keeping its docstring.

    Every definition of a name is rewritten (a function defined in both
    branches of an if has two). A lambda's expression becomes None. The new
    body always goes on its own lines, positions are read in UTF-8 bytes as
    ast reports them, and only real line breaks count as lines (a form feed
    does not), so one-line functions, non-ASCII text and bodies on the
    signature's closing line are rewritten correctly. Line endings are
    normalised to newlines first, which Python's own tokenizer also does.

    Returns the new source. Raises KeyError for an unknown name and
    SyntaxError when the result does not compile or is not what was asked for.
    """
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    funcs, _ = python_definitions(source)
    lines = [l + "\n" for l in source.split("\n")]
    lines[-1] = lines[-1][:-1]
    starts = _char_offsets(lines)
    edits = []
    for q in qualnames:
        for node in funcs[q]:
            if isinstance(node, ast.Lambda):
                b = node.body
                edits.append((_position(lines, starts, b.lineno, b.col_offset),
                              _position(lines, starts, b.end_lineno, b.end_col_offset), "None"))
                continue
            body = list(node.body)
            doc = body[0] if _is_docstring(body[0]) else None
            first = body[0]
            start = starts[first.lineno - 1]
            before = source[start:_position(lines, starts, first.lineno, first.col_offset)]
            def_line = lines[node.lineno - 1]
            lead = def_line[:len(def_line) - len(def_line.lstrip())]
            indent = lead + ("\t" if "\t" in lead else "    ")
            new_body = ""
            if doc is not None:
                new_body += indent + ast.get_source_segment(source, doc) + "\n"
            new_body += indent + "return None\n"
            text = (before.rstrip() + "\n" + new_body) if before.strip() else new_body
            edits.append((start, starts[node.end_lineno], text))
    result = source
    for start, end, text in sorted(edits, key=lambda e: -e[0]):
        result = result[:start] + text + result[end:]
    compile(result, "<probe>", "exec")
    # Check the rewrite did what it says: the same functions, and the named ones neutral.
    new_funcs, _ = python_definitions(result)
    if sorted(new_funcs) != sorted(funcs) or any(
            len(new_funcs[q]) != len(funcs[q]) or not all(_is_neutral(n) for n in new_funcs[q]) for q in qualnames):
        raise SyntaxError("the probe rewrite of %s did not give the expected source" % ", ".join(qualnames))
    return result


def probe_targets(py_functions, cfg):
    targets = []
    for path in sorted(py_functions):
        for q in py_functions[path]:
            short_name = q.split(".")[-1]
            if any(fnmatch.fnmatchcase(short_name, pat) for pat in cfg["probe_ignore"]):
                continue
            targets.append((path, q))
    return targets


def _neutral_dir(state):
    """A worktree folder whose name does not tell the tests which commit it holds."""
    return os.path.join(state["tmp_parent"], "wt-" + os.urandom(4).hex())


def run_probe(cfg, repo, head, state, tests_changed, head_passed_ids, targets, budget, say):
    """Run the changed tests with neutral bodies. Returns the list of (path, name) not covered.

    The probe worktree was made before the first test run (evaluate); each
    rewrite is committed there, and the folder is checked before each run.
    """
    probe_dir, seal = _probe_worktree(repo, head, state)
    groups = [[t] for t in targets] if cfg["probe_scope"] == "each" else [targets]
    originals, encodings = {}, {}
    for path, _ in targets:
        # Read the file in its declared encoding (a coding line, else UTF-8).
        try:
            with tokenize.open(os.path.join(probe_dir, *path.split("/"))) as fh:
                originals[path] = fh.read()
                encodings[path] = fh.encoding
        except (SyntaxError, UnicodeDecodeError, LookupError):
            state["probe"] = "broken"
            raise GuardStop(ERROR, "probe-broken", MESSAGES["probe-broken"].format(functions=path), HINTS["probe-broken"])
    sub = SubBudget(cfg["probe_time_budget_seconds"], budget)
    not_covered = []
    first = True
    names_all = ", ".join(q for _, q in targets)

    def write(path, text):
        with open(os.path.join(probe_dir, *path.split("/")), "w", encoding=encodings[path], newline="") as fh:
            fh.write(text)

    for group in groups:
        names = ", ".join(q for _, q in group)
        by_file = {}
        for path, q in group:
            by_file.setdefault(path, []).append(q)
        # The folder must still be what the guard left there (version 0.2.2).
        seal.verify()
        try:
            for path, src in originals.items():
                if path not in by_file:
                    write(path, src)
            for path, qs in by_file.items():
                write(path, neutralise_python(originals[path], qs))
        except (SyntaxError, KeyError, ValueError, UnicodeEncodeError):
            state["probe"] = "broken"
            raise GuardStop(ERROR, "probe-broken", MESSAGES["probe-broken"].format(functions=names), HINTS["probe-broken"])
        written = sorted(originals)
        # The first rewrite is committed on top of the head, each later one replaces it.
        seal.seal(seal_commit(probe_dir, written, amend=not first), written)
        try:
            res = run_tests(cfg, probe_dir, tests_changed, "probe", sub, repo, state, do_setup=first)
        except BudgetExceeded as exc:
            if exc.phase == "probe-own":
                state["probe"] = "timeout"
                raise GuardStop(TIMEOUT, "probe-time-budget",
                                MESSAGES["probe-time-budget"].format(seconds=cfg["probe_time_budget_seconds"], functions=names_all),
                                HINTS["probe-time-budget"])
            raise
        finally:
            seal.after_run()
        first = False
        if res["records"] is not None:
            noticed = [r["id"] for r in res["records"] if r["id"] in head_passed_ids and r["outcome"] in ("failed", "error")]
            # The rewrite compiled (neutralise_python checks it), so a test file that
            # now fails to load depends on the new code: that counts as noticed.
            loads = [r for r in res["records"] if r["file_level"]]
            covered = bool(noticed) or bool(loads)
        else:
            covered = res["rc"] != 0
        say("probe: %s with an empty body -> %s (%.2f s)" % (names, "noticed by the tests" if covered else "NOT noticed by the tests", res["secs"]))
        if not covered:
            not_covered.extend(group)
            if cfg["probe_scope"] == "each":
                # One function nobody notices already stops the change; do not spend the
                # budget on the others (version 0.3.1, D9 of the 0.3.0 audit).
                break
    return not_covered


def _probe_worktree(repo, head, state):
    """The probe worktree evaluate prepared, or a new one, sealed at the head commit."""
    if not state.get("probe_dir"):
        probe_dir = _neutral_dir(state)
        add_worktree(repo, head, probe_dir)
        state["worktrees"].append(probe_dir)
        state["probe_dir"] = probe_dir
        state["probe_seal"] = WorktreeSeal(probe_dir, "probe")
        state["probe_seal"].seal(head)
    return state["probe_dir"], state["probe_seal"]


def run_probe_command(cfg, repo, head, state, tests_changed, names, files, budget, say):
    probe_dir, seal = _probe_worktree(repo, head, state)
    seal.verify()
    sub = SubBudget(cfg["probe_time_budget_seconds"], budget)
    command = fill_placeholders(cfg["probe_command"], {
        "functions": " ".join(shlex.quote(n) for n in sorted(names)),
        "files": " ".join(shlex.quote(f) for f in files),
        "python": shlex.quote(sys.executable),
    })
    env = command_environment(cfg)
    try:
        rc, out, secs = run_shell(command, probe_dir, sub, "probe", env)
    except BudgetExceeded as exc:
        if exc.phase == "probe-own":
            state["probe"] = "timeout"
            raise GuardStop(TIMEOUT, "probe-time-budget",
                            MESSAGES["probe-time-budget"].format(seconds=cfg["probe_time_budget_seconds"], functions=", ".join(sorted(names))),
                            HINTS["probe-time-budget"])
        raise
    say("probe command: exit %d (%.2f s)" % (rc, secs))
    return rc == 0


# --------------------------------------------------------------------------
# Notes from the test diff (never change the result)
# --------------------------------------------------------------------------

def test_diff_notes(diff, edited_tests, deleted_tests, added_tests, names_added, snapshot_files, protected):
    notes = []
    for path in sorted(edited_tests):
        d = diff.get(path, {"added": [], "removed": []})
        removed = sum(1 for l in d["removed"] if ASSERT_LINE_RX.search(l))
        added = sum(1 for l in d["added"] if ASSERT_LINE_RX.search(l))
        if removed > added:
            notes.append(("assertions-removed", "assertion lines were removed from %s (%d removed, %d added)" % (path, removed, added)))
        gone = set()
        for l in d["removed"]:
            m = TEST_DEF_RX.match(l)
            if m:
                gone.add(next(g for g in m.groups() if g))
        for l in d["added"]:
            m = TEST_DEF_RX.match(l)
            if m:
                gone.discard(next(g for g in m.groups() if g))
        for name in sorted(gone):
            notes.append(("test-deleted", "test %s was deleted from %s" % (name, path)))
    for path in sorted(deleted_tests):
        notes.append(("test-deleted", "test file %s was deleted" % path))
    for path in sorted(set(edited_tests) | set(added_tests)):
        d = diff.get(path, {"added": [], "removed": []})
        if any(SKIP_MARKER_RX.search(l) for l in d["added"]):
            notes.append(("skip-marker-added", "a skip or expected-failure marker was added in %s" % path))
        mocked = set()
        for l in d["added"]:
            if MOCK_RX.search(l):
                for name in names_added:
                    if re.search(r"\b%s\b" % re.escape(name), l):
                        mocked.add(name)
        for name in sorted(mocked):
            notes.append(("mocks-new-code", "%s replaces %s, a name this change adds, with a mock" % (path, name)))
    if snapshot_files and protected:
        notes.append(("snapshot-changed", "snapshot or golden files changed together with protected code: %s; read that diff" % ", ".join(sorted(snapshot_files)[:5])))
    return notes


# --------------------------------------------------------------------------
# The evaluation
# --------------------------------------------------------------------------

def short(sha):
    return sha[:12] if sha else "-"


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def list_files(paths, limit=3):
    shown = ", ".join(paths[:limit])
    if len(paths) > limit:
        shown += " and %d more" % (len(paths) - limit)
    return shown


def add_note(state, code, text):
    if (code, text) not in state["notes"]:
        state["notes"].append((code, text))


def head_failures(res):
    if res["records"] == []:
        # An empty report (pytest exit 5, no tests collected) is judged as no-test-collected.
        return False
    if res["rc"] != 0:
        return True
    if res["records"]:
        return any(r["outcome"] in ("failed", "error") for r in res["records"])
    return False


def same_python(repo, base, head, path):
    """True when both versions of a Python file parse to the same syntax tree."""
    old, new = show_file(repo, base, path), show_file(repo, head, path)
    if old is None or new is None:
        return False
    try:
        return ast.dump(ast.parse(old)) == ast.dump(ast.parse(new))
    except (SyntaxError, ValueError):
        return False


def same_script_line(repo, base, head, path):
    """False when either version starts with '#!' and its first line changed, byte for byte.

    The system reads the interpreter from that line, so a carriage return or a
    trailing space there changes what runs, although the syntax tree is the same.
    """
    old, new = show_file(repo, base, path) or b"", show_file(repo, head, path) or b""
    if not (old.startswith(b"#!") or new.startswith(b"#!")):
        return True
    return old.split(b"\n", 1)[0] == new.split(b"\n", 1)[0]


def has_generated_marker(repo, rev, path, markers):
    data = show_file(repo, rev, path)
    if data is None:
        return False
    first_lines = "\n".join(data.decode("utf-8", "replace").splitlines()[:5])
    return any(m in first_lines for m in markers)


def test_material_rule(tests_patterns, tests_changed):
    """Whether an edited file outside the protected paths is test material (version 0.3.2, RC-N1).

    True for a file under the literal folder of a tests pattern (tests/ for
    tests/**/test_*.py) or in the folder of a changed test file or below it.
    Files that match tests or test_support are laid over anyway. A test file in
    the top folder of the repository makes no folder test material.
    """
    folders = set()
    for pattern in tests_patterns:
        pat = pattern.strip()
        while pat.startswith("./"):
            pat = pat[2:]
        pat = pat.lstrip("/")
        if pat.endswith("/"):
            pat += "**"
        if "/" not in pat:
            continue
        prefix = []
        for part in pat.split("/")[:-1]:
            if "*" in part or "?" in part:
                break
            prefix.append(part)
        if prefix:
            folders.add("/".join(prefix) + "/")
    for path in tests_changed:
        folder = os.path.dirname(path)
        if folder:
            folders.add(folder + "/")
    # Every conftest.py is pytest's own test material, wherever it lies (version 0.3.3, C-N1).
    return lambda path: os.path.basename(path) == "conftest.py" or any(path.startswith(f) for f in folders)


def protected_pattern_problems(cfg, files):
    """What each protected pattern protects among these files (versions 0.3.1 and 0.3.2).

    Returns (unused, covered, protects_any): the patterns that match no file,
    the patterns whose every file also matches a tests pattern (the guard reads
    a file that matches both as a test, so such a pattern protects nothing), and
    whether any file is protected at all. Overlap as such is normal
    (src/**/*_test.go next to src/**); only full cover is reported.
    """
    tests_rx = [glob_to_regex(p) for p in cfg["tests"]]
    unused, covered, protects_any = [], [], False
    for pattern in cfg["protected"]:
        rx = glob_to_regex(pattern)
        hits = [f for f in files if rx.match(f)]
        if not hits:
            unused.append(pattern)
        elif all(matches_any(f, tests_rx) for f in hits):
            covered.append(pattern)
        else:
            protects_any = True
    return unused, covered, protects_any


def config_repair(args, repo, head, changes, head_files, say, state):
    """EXEMPT config-repair for a change that only repairs a pattern problem of the base's rules (version 0.3.2, RC-N2).

    The change must touch nothing but the configuration file, and the head's
    configuration must load and protect files with every pattern it names.
    Returns the outcome, or None when the change is not such a repair.
    """
    rel = getattr(args, "config_rel", None)
    if not rel or [p for _, p in changes] != [rel]:
        return None
    data = show_file(repo, head, rel)
    if data is None:
        return None
    try:
        head_cfg = parse_config(data, "%s on the head commit" % rel)
    except GuardStop:
        return None
    unused, _, protects_any = protected_pattern_problems(head_cfg, head_files)
    if unused or not protects_any:
        return None
    say("config: the rules on the base commit have a protected pattern that protects nothing; this change repairs %s and changes nothing else" % rel)
    add_note(state, "config-repair", "the configuration on the base commit has a protected pattern that protects nothing; this change only repairs it, and the repaired rules apply from the next change on")
    return GuardStop(EXEMPT, "config-repair",
                     "The configuration on the base commit has a protected pattern that protects nothing, and this change only repairs %s so that every pattern protects files, so the guard passed it without running any test." % rel)


def evaluate(args, cfg, state, say):
    # The top folder of the checkout (version 0.3.2, RC-N3): git reads the paths of
    # a diff from the folder it runs in, so a run started in a subfolder looked at
    # nothing there.
    repo = getattr(args, "top", None) or args.repo
    base_given = getattr(args, "base_sha", None) or resolve(repo, args.base, "base")
    head = getattr(args, "head_sha", None) or resolve(repo, args.head, "head")
    mb = git(repo, "merge-base", base_given, head, check=False)
    if mb.returncode != 0:
        shallow = git(repo, "rev-parse", "--is-shallow-repository", check=False).stdout.decode().strip() == "true"
        if shallow:
            raise GuardStop(ERROR, "git", "This clone is shallow and does not hold the merge base of the base and head commits, so the guard cannot judge this change; fetch the full history (fetch-depth 0).")
        raise GuardStop(ERROR, "git", "The base and head commits share no history, so the guard cannot tell what this change is.")
    base = mb.stdout.decode().strip()
    state["base"], state["head"] = base, head
    note = "" if base == base_given else " (merge base of %s)" % short(base_given)
    say("base %s%s, head %s" % (short(base), note, short(head)))

    protected_rx = [glob_to_regex(p) for p in cfg["protected"]]
    exempt_rx = [glob_to_regex(p) for p in cfg["exempt"]]
    tests_rx = [glob_to_regex(p) for p in cfg["tests"]]
    support_rx = [glob_to_regex(p) for p in cfg["test_support"]]
    snapshot_rx = [glob_to_regex(p) for p in cfg["snapshot_patterns"]]
    guard_rx = [glob_to_regex(p) for p in cfg["guard_files"] + [getattr(args, "config_rel", None) or "change-guard.json"]]

    raw = raw_changes(repo, base, head)
    renames = renamed_from(raw)
    renamed_old = set(renames.values())
    changes = changed_files(repo, base, head, raw)
    tests_changed, protected, exempt, other, support = [], [], [], [], []
    protected_status, test_status = {}, {}
    for status, path in changes:
        if matches_any(path, tests_rx):
            test_status[path] = status
            if status != "D":
                tests_changed.append(path)
        elif matches_any(path, exempt_rx):
            exempt.append(path)
        elif matches_any(path, protected_rx):
            protected.append(path)
            protected_status[path] = status
        else:
            other.append(path)
        if matches_any(path, support_rx) and status != "D" and path not in tests_changed:
            support.append(path)
    state["protected_files"] = len(protected)
    state["test_files"] = len(tests_changed)
    say("changed: %s, %s, %s, %s" % (
        plural(len(protected), "protected file"), plural(len(tests_changed), "test file"),
        plural(len(exempt), "exempt file"), plural(len(other), "other file")))
    for label, items in (("protected", protected), ("tests", tests_changed), ("exempt", exempt), ("other", other)):
        if items:
            say("  %-9s %s" % (label + ":", list_files(items, 6)))
    guard_changed = [p for _, p in changes if matches_any(p, guard_rx)]
    if guard_changed:
        add_note(state, "guard-changed", "this change edits the guard's own files (%s); the guard ran with the base commit's rules, and a person who owns the guard should review that edit" % list_files(guard_changed, 4))

    # The documented skip step comes before any test run.
    skip_by = (args.skip_by or "").strip()
    skip_reason = " ".join((args.skip_reason or "").split())
    # Empty values (an unset CI variable) mean no skip was asked for.
    if skip_by or skip_reason:
        state["skipped_by"], state["skip_reason"] = skip_by, skip_reason
        if not skip_by:
            raise GuardStop(STOPPED, "skip-no-who",
                            "A skip was requested without naming who skipped, so the skip was refused and the guard did not pass this change.",
                            "Skips need a person and a reason; see the skip step in the README.")
        if len(skip_reason) < cfg["skip_reason_min_length"]:
            raise GuardStop(STOPPED, "skip-no-reason",
                            "A skip was requested by %s without a reason of at least %d characters, so the skip was refused and the guard did not pass this change." % (skip_by, cfg["skip_reason_min_length"]),
                            "Give a reason of at least that length; on GitHub and GitLab, a line in the description that starts with 'Change-Guard-Skip-Reason:'.")
        raise GuardStop(SKIPPED, "skip",
                        "The guard was skipped by %s with the reason \"%s\", and this run is recorded in the log." % (skip_by, skip_reason))

    # A protected pattern that matches no file protects nothing, which is almost
    # always a typo (version 0.3.1, finding I7): say so, and fail in block mode.
    modes = {base: tree_modes(repo, base), head: tree_modes(repo, head)}
    tree_files = set(modes[base]) | set(modes[head])
    unused, covered, protects_any = protected_pattern_problems(cfg, tree_files)
    if unused or not protects_any:
        config_name = getattr(args, "config_rel", None) or "the configuration file"
        repair = config_repair(args, repo, head, changes, set(modes[head]), say, state)
        if repair is not None:
            raise repair
        hint = ("Fix or remove the pattern in a change that touches only %s (for example src/** for every file under src/); "
                "such a change passes as EXEMPT (config-repair). Or use the documented skip step." % config_name)
        if unused:
            raise GuardStop(ERROR, "config",
                            "The protected pattern%s %s match%s no file of the base or the head commit, so %s nothing; the guard refuses to run with a pattern that cannot be meant." % (
                                "s" if len(unused) > 1 else "", ", ".join("'%s'" % p for p in unused),
                                "" if len(unused) > 1 else "es", "they protect" if len(unused) > 1 else "it protects"),
                            hint)
        raise GuardStop(ERROR, "config",
                        "Every file under the protected pattern%s %s also matches a tests pattern, so the guard treats each of them as a test and the configuration protects nothing." % (
                            "s" if len(covered) > 1 else "", ", ".join("'%s'" % p for p in covered)),
                        hint.replace("Fix or remove the pattern", "Narrow the tests patterns (for example tests/**/test_*.py)"))
    if covered:
        add_note(state, "tests-cover-protected", "every file under the protected pattern%s %s also matches a tests pattern, so the guard treats those files as tests and that pattern protects nothing" % (
            "s" if len(covered) > 1 else "", ", ".join("'%s'" % p for p in covered)))

    if not changes:
        raise GuardStop(OUT_OF_SCOPE, "no-change", "The head commit changes no file against the base, so there is nothing to check.")
    if not protected:
        if exempt and not other and not tests_changed:
            raise GuardStop(EXEMPT, "exempt-only",
                            "Every changed file is on the exempt list, so the guard passed this change untouched without running any test.")
        raise GuardStop(OUT_OF_SCOPE, "no-protected-change",
                        "No changed file is under a protected path, so the guard passed this change without running any test.")

    # Automatic exemptions, before the no-test rule. Each passes a change only
    # when that change cannot alter behaviour.
    auto = cfg["auto_exempt"]
    if "rename" in auto:
        prot_raw = [(s, o, n) for s, o, n in raw if (o in protected_status or n in protected_status)]
        if prot_raw and all(s == "R100" for s, _, _ in prot_raw):
            raise GuardStop(EXEMPT, "pure-rename", MESSAGES["pure-rename"])
    if "whitespace" in auto and all(protected_status[p] == "M" and p.endswith(".py") for p in protected):
        # Only Python files, and only when both versions parse to the same syntax tree
        # (indentation and the text of strings are behaviour) and git -w finds no other
        # change (comments). In other files a carriage return or a trailing space can be
        # behaviour (shell scripts, Makefiles, YAML block text), so they need a test,
        # the skip step or the exempt list (version 0.2.2).
        any_ws = git(repo, "diff", "-w", "--ignore-blank-lines", "--no-renames", "--no-color", "--no-textconv",
                     "--no-ext-diff", base, head, "--", *protected).stdout
        if not any_ws.strip() and all(same_python(repo, base, head, p) and same_script_line(repo, base, head, p)
                                      for p in protected):
            raise GuardStop(EXEMPT, "whitespace-only", MESSAGES["whitespace-only"])
    if "generated" in auto and cfg["generated_markers"]:
        # The marker must already be on the base version: a change cannot exempt itself by adding one.
        live = [p for p in protected if protected_status[p] != "D"]
        # A deleted protected file has no marker and is not generated (version 0.3.1, M1).
        if live and len(live) == len(protected) and all(protected_status[p] == "M"
                        and has_generated_marker(repo, base, p, cfg["generated_markers"])
                        and has_generated_marker(repo, head, p, cfg["generated_markers"]) for p in live):
            raise GuardStop(EXEMPT, "generated", MESSAGES["generated"])

    if not tests_changed:
        raise GuardStop(STOPPED, "no-test",
                        "This change touches %s (%s) but brings no new or changed test file, so nothing shows that its behaviour is tested." % (
                            plural(len(protected), "protected file"), list_files(protected)),
                        "Add or change a test that fails without this change and passes with it, or use the documented skip step.")

    # What the change adds, and notes on the test diff.
    live_protected = [(protected_status[p], p) for p in protected if protected_status[p] != "D"]
    diff = diff_by_file(repo, base, head, list(protected) + list(test_status))
    modified_code, param_owners = [], {}
    names_added, py_functions = added_symbols(repo, base, head, live_protected, diff, renames, modified=modified_code,
                                              owners=param_owners)
    # Files the base lacks because the change adds them. Version 0.3.1 (finding I4):
    # only protected ones; a test file or a helper the change adds is laid over the
    # base, so it is never missing there, and its name in an error explains nothing.
    added_paths = [p for st, p in changes if st in ("A", "R") and p in protected_status]
    added_other = [p for st, p in changes if st in ("A", "R") and p not in protected_status]
    edited_other = [p for st, p in changes if st == "M" and p not in protected_status]
    if not cfg["overlay_added_files"]:
        # Not laid over, so really missing on the base.
        added_paths += [p for p in added_other if not matches_any(p, tests_rx) and p not in support]
    edited_tests = [p for p, s in test_status.items() if s in ("M", "R")]
    if cfg["notes"]:
        snapshot_files = [p for _, p in changes if matches_any(p, snapshot_rx)]
        for code, text in test_diff_notes(
                diff,
                edited_tests,
                [p for p, s in test_status.items() if s == "D" and p not in renamed_old],
                [p for p, s in test_status.items() if s == "A"],
                names_added, snapshot_files, protected):
            add_note(state, code, text)

    budget = state["budget"]
    tmp_parent = tempfile.mkdtemp(prefix="change-guard-")
    state["tmp_parent"] = tmp_parent
    # Neutral folder names: a test must not learn from its path which commit it runs on.
    head_dir = _neutral_dir(state)
    base_dir = _neutral_dir(state)
    has_report = cfg["report_format"] != "none"

    # Whether the probe will need a worktree, known before any test runs.
    py_targets = probe_targets(py_functions, cfg)
    has_py = any(p.endswith(".py") for _, p in live_protected)
    early_mode = cfg["probe"] if cfg["probe"] != "auto" else ("python" if has_py else "off")
    probe_needed = (early_mode == "python" and bool(py_targets)) or (early_mode == "command" and bool(names_added))

    # Every worktree is made before the first test command runs (version 0.2.2), so
    # nothing the tests leave in the repository's .git can change how they are
    # checked out, and the guard's own changes are committed in each, so the three
    # look alike to git status and git log -1.
    add_worktree(repo, head, head_dir)
    state["worktrees"].append(head_dir)
    seal_commit(head_dir)
    add_worktree(repo, base, base_dir)
    state["worktrees"].append(base_dir)
    overlay = [(p, head, p) for p in list(tests_changed) + support]
    if cfg["overlay_added_files"]:
        # Version 0.3.1 (finding I3 of the 0.3.0 audit): every file the change adds
        # outside the protected paths is laid over the base too. Version 0.3.2
        # (RC-N1): a file the change edits there is laid over only when it is test
        # material (test_material), so the base keeps its own helpers, data files and
        # build files, and the old protected code meets the files it was written for.
        material = test_material_rule(cfg["tests"], tests_changed)
        overlay += [(p, head, p) for p in added_other + [p for p in edited_other if material(p)]
                    if not matches_any(p, tests_rx) and p not in support]
    # A renamed protected file keeps its old content on the base, under its new
    # name: the rename is not the behaviour, so tests that import the new name
    # meet the old code.
    overlay += [(new, base, renames[new]) for st, new in live_protected
                if st == "R" and show_file(repo, base, new) is None]
    written = []
    for path, rev, source in overlay:
        entry_mode = modes[rev].get(source)
        if entry_mode == "160000":
            # A submodule pointer has no content to write (version 0.3.2, RC-N8).
            continue
        data = git(repo, "show", "%s:%s" % (rev, source)).stdout
        target = os.path.join(base_dir, *path.split("/"))
        # A file that became a folder, or a folder that became a file (version 0.3.1, M7).
        # A link on the way is replaced too, so nothing is written through it (version 0.3.2, RC-N8).
        parts = path.split("/")
        for i in range(1, len(parts)):
            parent = os.path.join(base_dir, *parts[:i])
            if os.path.islink(parent) or (os.path.lexists(parent) and not os.path.isdir(parent)):
                os.remove(parent)
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        elif os.path.lexists(target):
            os.remove(target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if entry_mode == "120000":
            os.symlink(data.decode("utf-8", "surrogateescape"), target)
        else:
            with open(target, "wb") as fh:
                fh.write(data)
            if entry_mode == "100755":
                os.chmod(target, 0o755)
        written.append(path)
    overlay_paths = list(dict.fromkeys(written))
    base_seal = WorktreeSeal(base_dir, "base")
    base_seal.seal(seal_commit(base_dir, overlay_paths), overlay_paths)
    if probe_needed:
        probe_dir = _neutral_dir(state)
        add_worktree(repo, head, probe_dir)
        state["worktrees"].append(probe_dir)
        state["probe_dir"] = probe_dir
        state["probe_seal"] = WorktreeSeal(probe_dir, "probe")
        state["probe_seal"].seal(head)
    # The tests run next: from here on the repository's hooks, configuration and
    # info folder are checked before every git command and at the end of the run.
    watch = RepoWatch(repo)
    state["repo_watch"] = watch
    _REPO_WATCHES.append(watch)

    # 1. The head's test files must pass on the head (one retry if allowed).
    head_res = run_tests(cfg, head_dir, tests_changed, "head", budget, repo, state)
    if head_failures(head_res) and cfg["head_retries"] >= 1:
        say("head: the changed test files failed (exit %d); running them once more" % head_res["rc"])
        retry = run_tests(cfg, head_dir, tests_changed, "head", budget, repo, state, do_setup=False)
        if not head_failures(retry):
            add_note(state, "flaky-on-head", "the changed tests failed once on the head and passed on the retry")
        head_res = retry
    if head_failures(head_res):
        for line in tail(head_res["out"], cfg["output_tail_lines"], tmp_parent):
            say("  head | " + line)
        raise GuardStop(STOPPED, "test-fails-on-head",
                        "The new or changed test files fail on the head commit (exit %d), so the change does not pass its own tests yet." % head_res["rc"],
                        "Run the listed test files locally on this branch and fix the failure. If they pass locally, "
                        "check that every environment variable they need is named in pass_env: the tests run with a "
                        "reduced environment (see pass_env in the README).")
    head_passed = []
    if has_report:
        if head_res["records"] is None:
            raise GuardStop(ERROR, "report-missing", MESSAGES["report-missing"].format(fmt=cfg["report_format"]), HINTS["report-missing"])
        if not [r for r in head_res["records"] if not r["file_level"]]:
            raise GuardStop(STOPPED, "no-test-collected", MESSAGES["no-test-collected"], HINTS["no-test-collected"])
        head_passed = [r for r in head_res["records"] if r["outcome"] == "passed" and not r["file_level"]]
        if not head_passed:
            raise GuardStop(STOPPED, "no-test-ran", MESSAGES["no-test-ran"], HINTS["no-test-ran"])
        say("head: %s passed in the changed test files (%.2f s)" % (plural(len(head_passed), "test"), head_res["secs"]))
    else:
        say("head: the changed test files pass (%.2f s)" % head_res["secs"])

    # 2. The head's test files, laid over a clean checkout of the base (prepared above), must fail.

    ctx = {"added": names_added, "added_paths": added_paths, "missing_rx": cfg["_missing_rx"],
           "env_patterns": cfg["_env_patterns"]}

    def base_run(do_setup=True):
        # The worktree must hold exactly what the guard put there (version 0.2.2).
        base_seal.verify()
        try:
            res = run_tests(cfg, base_dir, tests_changed, "base", budget, repo, state, do_setup=do_setup)
        finally:
            base_seal.after_run()
        if not has_report:
            return res, None
        records = res["records"]
        if records is None:
            # No report (for example a compile step failed first): the whole run
            # is one file-level error whose text is the end of the output.
            if res["rc"] == 0:
                records = []
            else:
                text = "\n".join(tail(res["out"], 40, tmp_parent))
                records = [_rec("run:base", "", "error", "no-report", text, True)]
        classes = classify_base(head_passed, records, ctx)
        for root in sorted({tmp_parent, os.path.realpath(tmp_parent)}, key=len, reverse=True):
            classes = {t: (c, d.replace(root, "<temp>")) for t, (c, d) in classes.items()}
        return res, classes

    # Edited files outside the protected paths that the base run kept as they are
    # on the base (version 0.3.3, C-N2): name them where the base run could not be used.
    kept = [p for p in edited_other if p not in overlay_paths]
    kept_hint = ("The base run kept %s as on the base; if the tests need the new version there, list those files under test_support. " % list_files(kept, 4)) if kept else ""
    base_res, classes = base_run()
    proof = new = other = []
    only_errored = False
    if has_report:
        proof, new, other = split_classes(classes, cfg)
        state["counts"] = (len(proof), len(new), len(other))
        state["classes"] = classes
        if args.explain:
            say("per-test results on the base commit:")
            for tid, (cls, detail) in classes.items():
                say("  %-22s %s%s" % (cls, tid, (" | " + detail) if detail else ""))
        stop = first_decision(classes, cfg)
        if stop:
            if stop.cause == "base-error-unrelated" and kept_hint:
                stop.hint = kept_hint + stop.hint
            raise stop
        say("base: %d by assertion or exception (proof), %d because new code is missing, %d for other reasons (%.2f s)" % (
            len(proof), len(new), len(other), base_res["secs"]))
        only_errored = bool(proof) and all(classes[t][0] == "errored-other" for t in proof)
        added_test_files = {p for p, s in test_status.items() if s == "A"}
        also_pass = [t["id"] for t in head_passed if classes.get(t["id"], ("",))[0] == "passed" and _in_files(t, added_test_files)]
        if also_pass:
            add_note(state, "passes-on-base", "%s in the new test files also %s on the base commit: %s" % (
                plural(len(also_pass), "test"), "passes" if len(also_pass) == 1 else "pass", list_files(also_pass, 3)))
    else:
        if base_res["rc"] == 0:
            raise GuardStop(STOPPED, "test-passes-on-base", MESSAGES["test-passes-on-base"], HINTS["test-passes-on-base"])
        say("base: the changed test files fail as required (exit %d, %.2f s)" % (base_res["rc"], base_res["secs"]))
        for line in tail(base_res["out"], min(6, cfg["output_tail_lines"]), tmp_parent):
            say("  base | " + line)
        suspects = [p for p in cfg["suspect_base_failure_patterns"] if p and p in base_res["out"]]
        if suspects:
            add_note(state, "suspect-base-output", "the base failure output contains %s; check that the test fails on the behaviour, not because the base does not build, a file is missing or a name the change adds does not exist there yet." % ", ".join("'%s'" % s for s in suspects[:6]))
        proof = ["exit-code"]

    # 3. A second base run must agree before anything passes.
    if cfg["base_repeats"] >= 2:
        again, classes2 = base_run(do_setup=False)
        if has_report:
            changed = [t for t in classes if classes[t][0] != classes2.get(t, ("",))[0]]
            flaky = bool(changed)
        else:
            flaky = (again["rc"] == 0) != (base_res["rc"] == 0)
        say("base, second run: %s (%.2f s)" % ("DIFFERENT result" if flaky else "same result", again["secs"]))
        if flaky:
            raise GuardStop(STOPPED, "flaky-on-base", MESSAGES["flaky-on-base"], HINTS["flaky-on-base"])

    # 4. The probe: every function the change adds must matter to the tests.
    probe_state = "none"
    non_py = sorted({os.path.splitext(p)[1] or p for _, p in live_protected if not p.endswith(".py")})
    mode = cfg["probe"]
    if mode == "auto":
        # The Python files are probed whenever there are any; other file types get a note.
        mode = "python" if has_py else "off"
        if non_py and (new or names_added):
            if mode == "python":
                add_note(state, "probe-partial", "the probe covered the Python files only; new code in %s files was not probed; set probe_command to your mutation tool to probe them" % ", ".join(non_py))
            else:
                add_note(state, "probe-unavailable", "the built-in probe covers Python only and this change touches %s files, so no probe ran; set probe_command to your mutation tool to probe them" % ", ".join(non_py))
    elif mode == "python" and non_py and names_added:
        add_note(state, "probe-partial", "the probe covered the Python files only; new code in %s files was not probed" % ", ".join(non_py))
    if mode == "python" and py_targets:
        not_covered = run_probe(cfg, repo, head, state, tests_changed, {t["id"] for t in head_passed}, py_targets, budget, say)
        if not_covered and (cfg["probe_scope"] == "each" or len(not_covered) == len(py_targets)):
            names = list_files([q for _, q in not_covered], 6)
            state["probe"] = "not-covered:" + ",".join(q for _, q in not_covered[:6])
            raise GuardStop(STOPPED, "probe-passes", MESSAGES["probe-passes"].format(functions=names), HINTS["probe-passes"])
        state["probe"] = "covered"
        probe_state = "covered"
    elif mode == "command" and names_added:
        files = [p for _, p in live_protected]
        if run_probe_command(cfg, repo, head, state, tests_changed, names_added, files, budget, say):
            state["probe"] = "command-covered"
            probe_state = "covered"
        else:
            state["probe"] = "not-covered:command"
            raise GuardStop(STOPPED, "probe-passes", MESSAGES["probe-passes"].format(functions=", ".join(sorted(names_added))), HINTS["probe-passes"])
    elif mode == "off" and new:
        state["probe"] = "unavailable" if cfg["probe"] == "auto" else "off"

    # 5. Edited existing tests: the version before the change, run on the head.
    if cfg["check_edited_tests"]:
        failing = []
        for path in edited_tests:
            original = show_file(repo, base, renames.get(path, path))
            if original is None:
                continue
            target = os.path.join(head_dir, *path.split("/"))
            with open(target, "rb") as fh:
                current = fh.read()
            with open(target, "wb") as fh:
                fh.write(original)
            try:
                res = run_tests(cfg, head_dir, [path], "head", budget, repo, state, do_setup=False)
            finally:
                with open(target, "wb") as fh:
                    fh.write(current)
            if head_failures(res):
                failing.append(path)
        if failing:
            add_note(state, "edited-test-would-fail", "the version of %s before this change fails on the head commit" % ", ".join(failing))
            if cfg["check_edited_tests"] == "stop":
                raise GuardStop(STOPPED, "edited-test-would-fail", MESSAGES["edited-test-would-fail"].format(files=", ".join(failing)), HINTS["edited-test-would-fail"])

    # 6. The verdict. Version 0.3.1 (findings D1 and I2 of the 0.3.0 audit): without
    # proof on the base, ok-new-code needs every missing name to be a function the
    # probe covered, and no edit to existing code that no test showed failing.
    unproven = []
    if not proof and new:
        probed = set()
        for _, q in py_targets:
            parts = q.split(".")
            # The function, and the classes it sits in (a new class whose methods were probed).
            probed.update(parts)
            probed.add(q)
        probed.update(param for param, funcs in param_owners.items() if funcs & {q for _, q in py_targets})
        for path in added_paths:
            if path.endswith(".py") and path in protected_status:
                module = python_module_name(path)
                probed.update((module, module.split(".")[-1]))
        matched = ctx.get("matched", {})
        loose = [t for t in new if classes[t][0] != "errored-new-symbol" or matched.get(t) not in probed]
        # Version 0.3.2: the verdict names the missing names and files, never a class of the guard.
        loose_files = sorted({matched[t] for t in loose if classes[t][0] == "errored-missing-file" and matched.get(t)})
        loose_names = sorted({matched[t] for t in loose if classes[t][0] != "errored-missing-file" and matched.get(t)})
        if probe_state == "covered":
            if loose_names:
                unproven.append("the names %s, which no probe covered" % list_files(loose_names, 4))
            if loose_files:
                unproven.append("the files %s, which no probe covered" % list_files(loose_files, 4))
            if loose and not loose_names and not loose_files:
                unproven.append("what the tests found missing on the base, which no probe covered")
        if modified_code:
            listed = list_files(modified_code, 4)
            unproven.append("the edits to existing code (%s)" % listed)
            add_note(state, "changed-code-unproven", "this change also edits existing code (%s), and no test showed failing on the base because of that edit; a reviewer should check it" % listed)
    verdict = final_decision(proof, new, probe_state, cfg, has_report=has_report, only_errored_proof=only_errored,
                             unproven=unproven)
    if kept_hint and has_report and verdict.cause in ("ok-unproven", "base-error-only") and any(classes[t][0] == "errored-unknown-name" for t in new):
        add_note(state, "kept-on-base", kept_hint.rstrip())
    raise verdict


def _in_files(test, files):
    g = _norm_group(test.get("group"))
    # A JVM or .NET report names the class (shop.BulkTest), not the file
    # (src/test/java/shop/BulkTest.java): the file then ends with the class (version 0.3.0).
    return bool(g) and any(_norm_group(f) == g or g.startswith(_norm_group(f) + ".") or _norm_group(f).endswith("." + g)
                           for f in files)


# --------------------------------------------------------------------------
# Output: log line, summary, exit code
# --------------------------------------------------------------------------

def clean(value):
    text = "-" if value is None or value == "" else str(value)
    return re.sub(r"[\t\r\n]+", " ", text)


def log_line(state, outcome, mode, ref, seconds):
    counts = state.get("counts")
    fields = [
        LOG_VERSION,
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        outcome.result, outcome.cause, mode, ref or "-",
        short(state.get("base")), short(state.get("head")),
        "%.2f" % seconds,
        state.get("protected_files", 0), state.get("test_files", 0),
        state.get("skipped_by"), state.get("skip_reason"),
        outcome.message,
        counts[0] if counts else "-", counts[1] if counts else "-", counts[2] if counts else "-",
        state.get("probe") or "-",
        ",".join(sorted({c for c, _ in state.get("notes", [])})) or "-",
    ]
    return "\t".join(clean(f) for f in fields)


def file_state(path):
    """(size, sha256) of a file, None when it does not exist, False when it cannot be read."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        return None
    except OSError:
        return False
    return len(data), hashlib.sha256(data).hexdigest()


class LogLock:
    """An exclusive lock next to the log, held from before the tests run until this run's line is written.

    Version 0.3.1 (finding D3 of the 0.3.0 audit): two guards in one checkout
    shared the log, and the slower one read the other's line as tampering and
    removed it. With the lock, a second run waits until the first has written its
    line; runs on one checkout take turns. Unix only (fcntl); elsewhere there is
    no lock and parallel runs on one log are not supported.

    Version 0.3.2 (RC-N7, RT-N1, RT-N7): only a lock that another process holds
    is waited for, on its own clock; when that wait runs out the run ends as
    ERROR log-busy and never runs unlocked. When the lock file cannot be made,
    or the file system refuses the lock, the run goes on at once without it and
    says why.
    """

    def __init__(self, log_path):
        self.path = log_path + ".lock"
        self.fh = None
        self.held = False

    def acquire(self, seconds, say=None):
        """Returns (status, detail): "locked"; "busy" when another run held the lock for
        the whole wait of at most `seconds`; "unlocked" with the cause when no lock can
        be had; "none" where the platform has no such lock (Windows)."""
        try:
            import fcntl
        except ImportError:
            return "none", ""
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            self.fh = open(self.path, "a+")
        except OSError as exc:
            self.fh = None
            return "unlocked", "the guard could not create the lock file next to the log (%s)" % (exc.strerror or exc)
        deadline = time.monotonic() + max(seconds, 0)
        told = False
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.held = True
                return "locked", ""
            except OSError as exc:
                if not (isinstance(exc, BlockingIOError) or exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN)):
                    self.release()
                    return "unlocked", "the file system refused a lock on the file next to the log (%s)" % (exc.strerror or exc)
                left = deadline - time.monotonic()
                if left <= 0:
                    return "busy", ""
                if say and not told:
                    say("waiting for another change guard run that writes to the same log (at most %.0f s)" % max(seconds, 0))
                    told = True
                time.sleep(min(0.2, left))

    def release(self):
        if self.fh is not None:
            try:
                self.fh.close()
            except OSError:
                pass
            self.fh = None
        self.held = False


def watch_files(paths):
    """Remember the state of files the tests must not change."""
    return {p: file_state(p) for p in dict.fromkeys(paths) if p}


def changed_files_since(watched):
    """The watched files that changed; text added at the end is removed again, a new file deleted."""
    changed = []
    for path, before in watched.items():
        if before is False:
            continue
        now = file_state(path)
        if now == before:
            continue
        changed.append(path)
        try:
            if before is None:
                os.remove(path)
            elif now:
                with open(path, "r+b") as fh:
                    if hashlib.sha256(fh.read(before[0])).hexdigest() == before[1]:
                        fh.truncate(before[0])
        except OSError:
            pass
    return changed


def shown_log(log_path, repo):
    """The log's path as printed: relative to the checkout when it lies inside it, else its file name."""
    return os.path.relpath(log_path, repo) if log_path.startswith(repo + os.sep) else os.path.basename(log_path)


def config_location(args):
    """The configuration as a path inside the repository (read from git), or None and a path on disk."""
    path = args.config
    if os.path.isabs(path):
        # Compare real paths: a repository reached through a symbolic link (/tmp
        # and /private/tmp on a Mac, a linked CI workspace) is still the
        # repository, and its configuration must still come from the base.
        real, repo_real = os.path.realpath(path), os.path.realpath(args.repo)
        if not real.startswith(repo_real + os.sep):
            return None, os.path.abspath(path)
        path = os.path.relpath(real, repo_real)
    rel = os.path.normpath(path).replace(os.sep, "/")
    if rel == ".." or rel.startswith("../"):
        return None, os.path.abspath(os.path.join(args.repo, path))
    return rel, None


def config_unloadable(args, stop, state, say):
    """The outcome when the configuration cannot be loaded (version 0.2.2).

    1. A skip request with a person and a reason is honoured and recorded, so
       the repair of a broken configuration can be let through on purpose.
    2. When the base commit's configuration does not load, the head's does, and
       the change touches nothing but that file, the change passes as EXEMPT
       config-repair: it changes no protected code, and the repaired rules
       apply from the next change on.
    3. Otherwise the configuration error stands.
    """
    skip_by = (args.skip_by or "").strip()
    skip_reason = " ".join((args.skip_reason or "").split())
    if skip_by or skip_reason:
        state["skipped_by"], state["skip_reason"] = skip_by, skip_reason
        add_note(state, "config-broken", "the configuration could not be loaded (%s)" % stop.message.rstrip("."))
        if not skip_by:
            return GuardStop(STOPPED, "skip-no-who",
                             "A skip was requested without naming who skipped, so the skip was refused and the guard did not pass this change.",
                             "Skips need a person and a reason; see the skip step in the README.")
        if len(skip_reason) < DEFAULTS["skip_reason_min_length"]:
            return GuardStop(STOPPED, "skip-no-reason",
                             "A skip was requested by %s without a reason of at least %d characters, so the skip was refused and the guard did not pass this change." % (skip_by, DEFAULTS["skip_reason_min_length"]),
                             "Give a reason of at least that length; on GitHub and GitLab, a line in the description that starts with 'Change-Guard-Skip-Reason:'.")
        return GuardStop(SKIPPED, "skip",
                         "The guard was skipped by %s with the reason \"%s\" while its configuration could not be loaded, and this run is recorded in the log." % (skip_by, skip_reason))
    repair_hint = ("Repair the configuration in a change that touches only %s, or use the documented skip step (a person and a reason)."
                   % (args.config_rel or "the configuration file"))
    if not args.config_rel or not getattr(args, "base_sha", None) or not getattr(args, "head_sha", None):
        return GuardStop(stop.result, stop.cause, stop.message, stop.hint or repair_hint)
    base_data = show_file(args.repo, args.base_sha, args.config_rel)
    if base_data is None:
        return GuardStop(stop.result, stop.cause, stop.message, stop.hint or repair_hint)
    mb = git(args.repo, "merge-base", args.base_sha, args.head_sha, check=False)
    if mb.returncode != 0:
        return GuardStop(stop.result, stop.cause, stop.message, stop.hint or repair_hint)
    base = mb.stdout.decode().strip()
    state["base"], state["head"] = base, args.head_sha
    changed = [p for _, p in changed_files(args.repo, base, args.head_sha)]
    head_data = show_file(args.repo, args.head_sha, args.config_rel)
    head_loads = False
    if head_data is not None:
        try:
            parse_config(head_data, "%s on the head commit" % args.config_rel)
            head_loads = True
        except GuardStop:
            head_loads = False
    if head_loads and changed == [args.config_rel]:
        say("config: %s on the base commit %s cannot be loaded; this change repairs it and changes nothing else" % (
            args.config_rel, short(args.base_sha)))
        add_note(state, "config-repair", "the configuration on the base commit could not be loaded (%s); this change only repairs it, and the repaired rules apply from the next change on" % stop.message.rstrip("."))
        add_note(state, "guard-changed", "this change edits the guard's own files (%s); a person who owns the guard should review that edit" % args.config_rel)
        return GuardStop(EXEMPT, "config-repair",
                         "The configuration on the base commit cannot be loaded and this change only repairs %s, so the guard passed it without running any test." % args.config_rel)
    return GuardStop(stop.result, stop.cause, stop.message, repair_hint)


def main(argv=None):
    p = argparse.ArgumentParser(description="Change guard: a change to protected paths must bring a test that fails on the base and passes on the head.")
    p.add_argument("--base", required=True, help="base commit, branch or tag (the merge base with --head is used)")
    p.add_argument("--head", required=True, help="head commit of the change")
    p.add_argument("--config", default="change-guard.json", help="configuration file (JSON), relative to --repo unless absolute")
    p.add_argument("--repo", default=".", help="path of the git repository (default: current folder)")
    # Any text here (version 0.3.2, RT-N5): case and spaces do not matter, and an
    # unknown mode fails closed below, the same as the variable and the key.
    p.add_argument("--mode", help="report or block; overrides the config and the CHANGE_GUARD_MODE variable")
    p.add_argument("--log", help="log file, overrides log_file in the config")
    p.add_argument("--ref", default=os.environ.get("CHANGE_GUARD_REF", ""), help="label for the log, for example pr-42")
    p.add_argument("--skip-by", default=os.environ.get("CHANGE_GUARD_SKIP_BY"), help="who skips the guard (documented skip step)")
    p.add_argument("--skip-reason", default=os.environ.get("CHANGE_GUARD_SKIP_REASON"), help="why the guard is skipped")
    p.add_argument("--time-budget", type=float, help="seconds, overrides time_budget_seconds")
    p.add_argument("--summary", help="append a Markdown summary to this file (for example $GITHUB_STEP_SUMMARY)")
    p.add_argument("--result-json", help="write the outcome as JSON to this file")
    p.add_argument("--explain", action="store_true", help="print the class of each changed test on the base commit")
    p.add_argument("--version", action="version", version="change-guard " + VERSION)
    args = p.parse_args(argv)
    args.repo = os.path.abspath(args.repo)
    args.config_rel, config_disk = config_location(args)

    lines = []

    def say(text):
        # File names and test ids come from the change: a line break in one must not
        # print a forged "result:" or "::error" line (version 0.3.1, M6).
        text = one_line(text)
        lines.append(text)
        print(text, flush=True)

    state = {"worktrees": [], "tmp_parent": None, "notes": [], "probe": None}
    # Case and spaces do not matter (version 0.3.1); an unknown mode is refused below and fails closed.
    mode = normal_mode(args.mode or os.environ.get("CHANGE_GUARD_MODE") or "report")
    bad_mode = None
    if mode not in ("report", "block"):
        # Fail closed: the owner meant some mode, and only block is safe (finding I1).
        bad_mode, mode = mode, "block"
    cfg = None
    watched = {}
    start = time.monotonic()

    def log_location():
        path = args.log or (cfg["log_file"] if cfg else DEFAULTS["log_file"])
        return path if os.path.isabs(path) else os.path.join(args.repo, path)

    log_lock = LogLock(os.devnull)
    lock_status = None
    # A cancel ends the run like any other: worktrees and test processes are
    # removed, and the run gets its verdict and its log line.
    previous = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[signum] = signal.signal(signum, _on_signal)
        except (ValueError, OSError):
            pass

    try:
        try:
            if os.path.isdir(args.repo) and all(os.path.exists(os.path.join(args.repo, n)) for n in ("HEAD", "objects", "refs")) \
                    and not os.path.exists(os.path.join(args.repo, ".git")):
                # Version 0.3.3 (C-N4): git runs with safe.bareRepository=explicit, so a bare clone is refused; say so.
                raise GuardStop(ERROR, "git", "The folder %s is a bare repository, which the guard does not support, so it cannot judge any change there." % args.repo,
                                "Point --repo at a checkout or a linked worktree (git worktree add) of the repository.")
            if not os.path.isdir(args.repo) or git(args.repo, "rev-parse", "--git-dir", check=False).returncode != 0:
                # Version 0.3.1 (D14): before, this read as a missing base commit.
                raise GuardStop(ERROR, "git", "The folder %s is not a git repository, so the guard cannot judge any change there." % args.repo,
                                "Run the guard with --repo pointing at the checkout of the repository.")
            top = git(args.repo, "rev-parse", "--show-toplevel", check=False)
            if top.returncode == 0 and top.stdout.strip():
                args.top = os.path.normpath(top.stdout.decode("utf-8", "replace").strip())
            if bad_mode is not None:
                say("change-guard %s | mode %s | the mode setting is not valid" % (VERSION, mode))
                raise GuardStop(ERROR, "config", "%s must be report or block, so the guard cannot run with %r; it fails the check until the value is fixed." % (
                                    "The option --mode" if args.mode else "CHANGE_GUARD_MODE", bad_mode),
                                "Set the mode to report or block (case and spaces do not matter).")
            if args.time_budget is not None and not (math.isfinite(args.time_budget) and args.time_budget > 0):
                # Version 0.3.2 (the rest of D11): before, --time-budget -5 ran and ended as TIMEOUT.
                say("change-guard %s | mode %s | the option --time-budget is not valid" % (VERSION, mode))
                raise GuardStop(ERROR, "config", "The option --time-budget must be a number of seconds above zero, so the guard cannot run with %s." % args.time_budget,
                                "Give --time-budget a number of seconds above zero, or leave it out to use time_budget_seconds.")
            # The rules come from the base commit, never from the change being judged.
            config_lines = []
            try:
                if args.config_rel:
                    args.base_sha = resolve(args.repo, args.base, "base")
                    args.head_sha = resolve(args.repo, args.head, "head")
                    cfg = load_config_from_commits(args.repo, args.base_sha, args.head_sha, args.config_rel,
                                                   config_lines.append, state)
                else:
                    cfg = load_config(config_disk)
                    config_lines.append("config: %s (a file outside the repository, named on the command line)" % config_disk)
            except GuardStop as stop:
                if stop.cause != "config":
                    raise
                if getattr(stop, "fail_closed", False):
                    mode = "block"
                # The skip request is read before the configuration is judged, and a
                # change that only repairs the base's configuration may pass (version 0.2.2).
                say("change-guard %s | mode %s | the configuration could not be loaded" % (VERSION, mode))
                raise config_unloadable(args, stop, state, say)
            if not args.mode and not (os.environ.get("CHANGE_GUARD_MODE") or "").strip():
                mode = cfg["mode"]
            if args.time_budget is not None:
                cfg["time_budget_seconds"] = args.time_budget
            say("change-guard %s | mode %s | time budget %.0f s | report %s" % (VERSION, mode, cfg["time_budget_seconds"], cfg["report_format"]))
            for text in config_lines:
                say(text)
            # One run at a time per log. The wait has its own clock, at most the time
            # budget, and the budget starts once the lock is held (version 0.3.2, RC-N7).
            log_lock.path = log_location() + ".lock"
            lock_status, lock_detail = log_lock.acquire(cfg["time_budget_seconds"], say)
            if lock_status == "busy":
                raise GuardStop(ERROR, "log-busy",
                                "Another change guard run held the log %s for longer than the time budget of %.0f seconds, so this run did not run the tests and wrote no line to that log." % (
                                    shown_log(log_location(), args.repo), cfg["time_budget_seconds"]),
                                "Run the job again when the other run has ended; runs that share one checkout and one log take turns.")
            if lock_status == "unlocked":
                add_note(state, "log-unlocked", "%s, so this run did not wait for other runs that write to the same log" % lock_detail)
            state["budget"] = Budget(cfg["time_budget_seconds"])
            # Files the tests must leave alone: the log, the summary, the CI
            # platform's control files and the guard's own scripts.
            watched = watch_files([log_location(), args.summary, os.path.abspath(__file__),
                                   os.path.join(HERE, "cg_unittest_report.py")]
                                  + [os.environ.get(name) for name in CI_CONTROL_FILES])
            evaluate(args, cfg, state, say)
            outcome = GuardStop(ERROR, "internal", "The guard ended without a result, which is a bug in the guard.")
        except GuardStop as stop:
            outcome = stop
        except GuardCancelled as exc:
            outcome = GuardStop(ERROR, "cancelled",
                                "The guard was cancelled (signal %d) before it reached a verdict, so nothing was judged." % exc.signum,
                                "Run the check again.")
        except BudgetExceeded as exc:
            outcome = GuardStop(TIMEOUT, "time-budget",
                                "The guard stopped after its time budget of %.0f seconds while running the tests on the %s, so it could not judge this change." % (
                                    cfg["time_budget_seconds"], {"probe": "head commit with the probe"}.get(exc.phase, exc.phase + " commit")),
                                "Raise time_budget_seconds, narrow test_command, or use the documented skip step.")
        except Exception as exc:  # never end a run without a verdict and a log line
            traceback.print_exc(file=sys.stderr)
            outcome = GuardStop(ERROR, "internal",
                                "The guard failed with %s (%s), which is a bug in the guard or an input it cannot handle, so nothing was judged." % (
                                    type(exc).__name__, " ".join(str(exc).split())[:200] or "no message"),
                                "Report this run with its output to the owner of the guard, or use the documented skip step.")
        finally:
            # Put back what the tests changed in the repository's .git before the
            # clean-up runs git again; the run then ends as ERROR tampered below.
            repo_watch = state.get("repo_watch")
            if repo_watch is not None:
                repo_watch.strict = False
                repo_watch.check()
            for wt in state["worktrees"]:
                remove_worktree(args.repo, wt)
            if state["worktrees"]:
                git(args.repo, "worktree", "prune", check=False)
            if state.get("tmp_parent"):
                shutil.rmtree(state["tmp_parent"], ignore_errors=True)
            if repo_watch is not None:
                repo_watch.check()
                if repo_watch in _REPO_WATCHES:
                    _REPO_WATCHES.remove(repo_watch)
    except Exception as exc:  # the clean-up itself failed
        outcome = GuardStop(ERROR, "internal", "The guard failed while cleaning up with %s (%s), so nothing was judged." % (
            type(exc).__name__, " ".join(str(exc).split())[:200] or "no message"))
    tampered = [os.path.basename(p) for p in changed_files_since(watched)]
    if state.get("repo_watch") is not None:
        tampered += [p for p in state["repo_watch"].changed if p not in tampered]
    if tampered:
        outcome = GuardStop(ERROR, "tampered", MESSAGES["tampered"].format(files=list_files(tampered, 6)),
                            HINTS["tampered"])
    seconds = time.monotonic() - start

    blocks = outcome.result not in LETS_THROUGH
    if outcome.result == TIMEOUT and cfg and cfg["on_timeout"] == "pass":
        blocks = False
    say("result: %s (%s)" % (outcome.result, outcome.cause))
    say("cause: " + outcome.message)
    for _, text in state["notes"]:
        say("note: " + text)
    if outcome.hint and outcome.result not in LETS_THROUGH:
        say("what to do: " + outcome.hint)
    if blocks and mode == "report":
        say("REPORT ONLY: in blocking mode this run would stop the merge; nothing is blocked now.")

    line = log_line(state, outcome, mode, args.ref, seconds)
    log_path = log_location()
    if lock_status is None:
        # A run that ended before the tests (for example a configuration error) still waits its turn.
        log_lock.path = log_path + ".lock"
        lock_status, _ = log_lock.acquire(30)
    if lock_status == "busy":
        # Writing now would change the log under the run that holds it, which reads that
        # as tampering (version 0.3.2, RT-N1): this run's line is printed instead.
        say("log: no line written to %s, because another change guard run still holds it; this run's line: %s" % (
            shown_log(log_path, args.repo), line.replace("\t", " | ")))
    else:
        try:
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            say("log: one line appended to %s" % shown_log(log_path, args.repo))
        except OSError as exc:
            say("log: could not write the log file (%s)" % exc)
    log_lock.release()

    if os.environ.get("GITHUB_ACTIONS") == "true":
        level = "error" if (blocks and mode == "block") else ("warning" if blocks else "notice")
        if outcome.cause == "ok-unproven":
            # Passed without proof (version 0.3.0): a reviewer should read the assertions.
            level = "warning"
        # The message holds file names and test output from the change: one line, and
        # "%" written as GitHub's escape, so the runner reads the message as written
        # (version 0.3.2, RC-N6).
        print("::%s title=change-guard %s::%s" % (level, outcome.result, one_line(outcome.message).replace("%", "%25")), flush=True)
    if args.summary:
        try:
            with open(args.summary, "a", encoding="utf-8") as fh:
                # Every text that can hold names or output from the change goes through
                # markdown_text, so it is shown as text (version 0.3.2, RC-N6).
                fh.write("### change-guard: %s (%s), mode %s\n\n%s\n\n" % (outcome.result, outcome.cause, mode, markdown_text(outcome.message)))
                for _, text in state["notes"]:
                    fh.write("- Note: %s\n" % markdown_text(text))
                if state["notes"]:
                    fh.write("\n")
                if state.get("classes"):
                    fh.write("| Test | Result on the base commit |\n|---|---|\n")
                    for tid, (cls, _) in list(state["classes"].items())[:50]:
                        fh.write("| %s | %s |\n" % (markdown_text(tid), markdown_text(cls)))
                    fh.write("\n")
                if outcome.hint and outcome.result not in LETS_THROUGH:
                    fh.write("What to do: %s\n\n" % markdown_text(outcome.hint))
                if blocks and mode == "report":
                    fh.write("Report only: in blocking mode this run would stop the merge.\n\n")
                # In a fenced block nothing is read as Markdown or HTML; the line is one line.
                fh.write("```\n%s\n```\n" % one_line(line).replace("```", "` ` `"))
        except OSError:
            pass
    if args.result_json:
        counts = state.get("counts")
        try:
            write_result_json(args.result_json, {
                "result": outcome.result, "cause": outcome.cause, "message": outcome.message,
                "mode": mode, "blocks": blocks and mode == "block", "seconds": round(seconds, 3),
                "base": state.get("base"), "head": state.get("head"),
                "protected_files": state.get("protected_files", 0), "test_files": state.get("test_files", 0),
                "skipped_by": state.get("skipped_by"), "skip_reason": state.get("skip_reason"),
                "note": "; ".join(t for _, t in state["notes"]),
                "notes": [c for c, _ in state["notes"]],
                "probe": state.get("probe"),
                "counts": list(counts) if counts else None,
                "classes": {k: v[0] for k, v in (state.get("classes") or {}).items()},
                "log_line": line,
            })
        except OSError as exc:
            say("result: could not write %s (%s)" % (args.result_json, exc))

    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except (ValueError, OSError, TypeError):
            pass
    if blocks and mode == "block":
        return 2 if outcome.result == ERROR else 1
    return 0


def write_result_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


if __name__ == "__main__":
    sys.exit(main())
