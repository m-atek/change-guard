#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Expeditious Software
#
# Builds the small git repository that .github/workflows/action-selftest.yml
# runs the action on. Demo project, no real data. Nothing is pushed.
#
#   bash tests/fixtures/action-selftest/build.sh TARGET_FOLDER
#
# main holds base/. Each folder in changes/ becomes one branch from main with
# one commit that lays those files over main. The commit ids are printed and,
# on GitHub Actions, written to the step outputs base, no_test,
# test_passes_on_base and real_test.

set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
target=${1:?usage: build.sh TARGET_FOLDER}
if [ -e "$target" ]; then
  echo "The folder $target already exists; choose a new one." >&2
  exit 1
fi

export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME="Demo Engineer" GIT_AUTHOR_EMAIL="demo@example.invalid"
export GIT_COMMITTER_NAME="Demo Engineer" GIT_COMMITTER_EMAIL="demo@example.invalid"

mkdir -p "$target"
git -C "$target" init --quiet -b main
cp -R "$here/base/." "$target/"
mv "$target/gitignore" "$target/.gitignore"
git -C "$target" add -A
git -C "$target" commit --quiet -m "Demo shop: first version"
base=$(git -C "$target" rev-parse HEAD)

commit_change() {
  local branch=$1 folder=$2 title=$3
  git -C "$target" checkout --quiet -B "$branch" main
  cp -R "$here/changes/$folder/." "$target/"
  git -C "$target" add -A
  git -C "$target" commit --quiet -m "$title"
  git -C "$target" rev-parse HEAD
}

no_test=$(commit_change demo/1-no-test 1-no-test "Bulk discount, no test")
weak=$(commit_change demo/2-test-passes-on-base 2-test-passes-on-base "Bulk discount with a test that also passes without it")
real=$(commit_change demo/3-real-test 3-real-test "Bulk discount with a test that checks it")
git -C "$target" checkout --quiet main

echo "base=$base"
echo "no_test=$no_test"
echo "test_passes_on_base=$weak"
echo "real_test=$real"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  {
    echo "base=$base"
    echo "no_test=$no_test"
    echo "test_passes_on_base=$weak"
    echo "real_test=$real"
  } >> "$GITHUB_OUTPUT"
fi
