#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
"""Per-test report for Python unittest, for the change guard (report_format "unittest-json").

Usage: python3 cg_unittest_report.py REPORT FILE [FILE ...]

Runs the given unittest files from the current folder, prints the usual
unittest output, and writes one JSON object per line to REPORT:

  {"id": ..., "file": ..., "outcome": "passed|failed|error|skipped",
   "type": exception class or "skip" or "expected-failure", "message": ...,
   "file_level": true when the file itself could not be loaded}

A file that cannot be imported (ImportError, SyntaxError and so on) becomes one
file-level record, so the guard can tell a load error from a failed assertion.
Exit code: 0 when everything passed or was skipped, 1 otherwise.
Python 3 standard library only.
"""

import importlib
import json
import os
import sys
import traceback
import unittest

RANK = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}


def module_name(path):
    p = path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    if p.endswith(".py"):
        p = p[:-3]
    return p.strip("/").replace("/", ".")


class Recorder(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = {}
        self.current_file = None
        self.bad = 0

    def put(self, test, outcome, err=None, kind=""):
        rid = test.id()
        message = ""
        if err is not None:
            etype, evalue = err[0], err[1]
            kind = etype.__name__
            message = "".join(traceback.format_exception_only(etype, evalue)).strip()
        elif kind in ("skip",):
            message = ""
        old = self.records.get(rid)
        if old and RANK[old["outcome"]] >= RANK[outcome]:
            return
        self.records[rid] = {
            "id": rid, "file": self.current_file, "outcome": outcome,
            "type": kind, "message": message,
            "file_level": type(test).__name__ == "_ErrorHolder",
        }

    def addSuccess(self, test):
        super().addSuccess(test)
        self.put(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.put(test, "failed", err)

    def addError(self, test, err):
        super().addError(test, err)
        self.put(test, "error", err)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.put(test, "skipped", kind="skip")
        self.records[test.id()]["message"] = str(reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.put(test, "skipped", kind="expected-failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.put(test, "failed", kind="unexpected-success")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            failed = issubclass(err[0], test.failureException)
            self.put(test, "failed" if failed else "error", err)


def main(argv):
    if len(argv) < 2:
        print("usage: cg_unittest_report.py REPORT FILE [FILE ...]", file=sys.stderr)
        return 2
    report, files = argv[0], argv[1:]
    sys.path.insert(0, os.getcwd())
    stream = unittest.runner._WritelnDecorator(sys.stdout)
    result = Recorder(stream, True, 1)
    loader = unittest.TestLoader()
    load_errors = []
    result.startTestRun()
    for path in files:
        result.current_file = path.replace("\\", "/")
        try:
            module = importlib.import_module(module_name(path))
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # a file that cannot be loaded at all
            text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            load_errors.append({"id": "load:" + result.current_file, "file": result.current_file,
                                "outcome": "error", "type": type(exc).__name__,
                                "message": text, "file_level": True})
            stream.writeln("ERROR: could not load %s: %s" % (path, text.splitlines()[-1] if text else type(exc).__name__))
            continue
        loader.loadTestsFromModule(module).run(result)
    result.stopTestRun()
    stream.writeln()
    result.printErrors()
    stream.writeln("Ran %d tests, %d failures, %d errors, %d skipped, %d files not loaded" % (
        result.testsRun, len(result.failures), len(result.errors), len(result.skipped), len(load_errors)))
    records = load_errors + list(result.records.values())
    tmp = report + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    os.replace(tmp, report)
    ok = not load_errors and result.wasSuccessful()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
