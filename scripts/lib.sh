# Shared plumbing for the scripts/ entry points - sourced by them, not run.
# POSIX sh, same dialect as .githooks/pre-push.
#
# `check <cmd...>` runs a command and records a failure instead of stopping,
# so one run reports everything that is wrong; `summary` prints the verdict
# and sets the exit code.

script_name="$(basename -- "$0")"

cd "$(dirname -- "$0")/.." || exit 1

# Bare npm tool names, not npx: npx ignores PATH and would network-install
# an *unpinned* version whenever ./node_modules is empty - which it always
# is in the devcontainer, where the image bakes the locked tools into
# /opt/npm-tools and puts them on PATH. Prepending ./node_modules/.bin
# covers clones outside the devcontainer after `npm ci`.
PATH="$PWD/node_modules/.bin:$PATH"

require_npm_tools() {
  missing=""
  for tool in prettier eslint markdownlint-cli2; do
    command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
  done
  if [ -n "$missing" ]; then
    echo "$script_name: not on PATH:$missing - run 'npm ci' first" \
      "(the devcontainer bakes them in)." >&2
    exit 1
  fi
}

failures=""

check() {
  echo ""
  echo "+ $*"
  "$@" || failures="$failures
  $*"
}

summary() {
  echo ""
  if [ -n "$failures" ]; then
    echo "$script_name: these commands failed:$failures" >&2
    exit 1
  fi
  echo "$script_name: all commands passed."
}
