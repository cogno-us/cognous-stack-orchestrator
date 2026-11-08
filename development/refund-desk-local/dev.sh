#!/usr/bin/env bash
# CORE-LOCAL / SYNTHETIC / NONPRODUCTION developer installation for the Refund Desk stack (plan #282 M1-4; contract: Amendment M4 in
# applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md). Nothing here authorizes anything. See README.md in this directory.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/../.." && pwd -P)"
TOOL="$HERE/devtool.py"
GIT_BASE="${COGNOUS_RD_DEV_GIT_BASE:-https://github.com/cogno-us}"
export GIT_TERMINAL_PROMPT=0

usage() {
  cat <<USAGE
Usage: dev.sh [--workspace DIR] COMMAND [options]

  setup                          create the isolated workspace, venv (hash-locked dependencies) and the four pinned checkouts
  env                            print 'export' lines (stack root, PYTHONPATH, PATH); use: eval "\$(dev.sh env)"
  demo [--name NAME]             run the routine / high / hold / mismatch / uncertain scenarios through the published CLI
  evidence --state DIR           list raw artifacts (paths, sizes, sha256, SQLite rows) under DIR inside the workspace state
  cleanup (--state-only|--all) [--yes]
                                 show the exact targets; remove only owned state with --yes (exit 3 without --yes)
  --help

Workspace: --workspace DIR, else \$COGNOUS_RD_DEV_WORKSPACE, else \$HOME/.cognous-refund-desk-dev (absolute path required).
Exit codes: 0 ok; 1 refused or failed; 2 usage error; 3 cleanup not executed (no --yes).
CORE-LOCAL development packaging only: synthetic, nonproduction, not independently qualified.
USAGE
}
die() { echo "REFUSED: $*" >&2; exit 1; }

WS=""
CMD=""
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --workspace) [ $# -ge 2 ] || { echo "dev.sh: --workspace needs a value" >&2; exit 2; }; WS="$2"; shift 2 ;;
    --workspace=*) WS="${1#--workspace=}"; shift ;;
    *) if [ -z "$CMD" ]; then CMD="$1"; else ARGS+=("$1"); fi; shift ;;
  esac
done
[ -n "$CMD" ] || { usage >&2; exit 2; }
[ -n "$WS" ] || WS="${COGNOUS_RD_DEV_WORKSPACE:-${HOME:-/nonexistent}/.cognous-refund-desk-dev}"

PY="${PYTHON:-python3}"
tool() { "$PY" -I "$TOOL" "$@"; }

case "$CMD" in
  setup)
    [ ${#ARGS[@]} -eq 0 ] || { echo "dev.sh setup: unexpected arguments: ${ARGS[*]}" >&2; exit 2; }
    for t in git "$PY"; do command -v "$t" >/dev/null 2>&1 || die "required tool not found: $t"; done
    "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || die "Python >= 3.11 required (found $("$PY" --version 2>&1))"
    "$PY" -c 'import venv, ensurepip' 2>/dev/null || die "the Python venv/ensurepip module is missing (on Debian/Ubuntu: apt install python3-venv)"
    PINS="$(tool pins --repo "$REPO")" || exit 1
    W="$(tool check-workspace --repo "$REPO" --workspace "$WS" --mode setup)" || exit 1
    tool marker --repo "$REPO" --workspace "$W" || exit 1
    echo "workspace: $W"
    if [ ! -x "$W/venv/bin/python" ]; then
      echo "creating venv ..."
      "$PY" -m venv "$W/venv" || die "venv creation failed"
    fi
    echo "installing hash-locked dependencies (repository .github/locks) ..."
    "$W/venv/bin/python" -m pip install --disable-pip-version-check --no-input --quiet --require-hashes --only-binary=:all: \
      -r "$REPO/.github/locks/cryptography-pydantic-pytest-513753.txt" -r "$REPO/.github/locks/jsonschema-424038.txt" \
      || { echo "dependency installation failed (state kept for inspection; see the message above)" >&2; exit 1; }
    mkdir -p "$W/stack"
    while read -r comp repo_name sha; do
      d="$W/stack/$comp"
      if [ -e "$d" ]; then
        head="$(git -C "$d" rev-parse HEAD 2>/dev/null)" || die "$comp: $d exists but is not a git checkout; refusing to touch it"
        [ "$head" = "$sha" ] || die "$comp: HEAD $head != pin $sha; refusing (never reset or cleaned automatically)"
        [ -z "$(git -C "$d" status --porcelain --untracked-files=no)" ] || die "$comp: tracked files are modified; refusing"
        echo "$comp: already at pin $sha"
      else
        echo "$comp: fetching $repo_name @ $sha ..."
        if ! { git init -q "$d" && git -C "$d" remote add origin "$GIT_BASE/$repo_name.git" \
               && { git -C "$d" fetch -q --depth 1 origin "$sha" || git -C "$d" fetch -q origin; } && git -C "$d" checkout -q --detach "$sha"; }; then
          rm -rf -- "$d"   # only the partial directory created by this run
          die "$comp: could not obtain $sha from $GIT_BASE/$repo_name.git"
        fi
        [ "$(git -C "$d" rev-parse HEAD)" = "$sha" ] || { rm -rf -- "$d"; die "$comp: fetched HEAD is not the pin"; }
        echo "$comp: at pin $sha"
      fi
    done <<<"$PINS"
    tool record --repo "$REPO" --workspace "$W" || exit 1
    echo "setup complete. Next: dev.sh demo   |   eval \"\$(dev.sh --workspace '$W' env)\""
    ;;
  env)
    [ ${#ARGS[@]} -eq 0 ] || { echo "dev.sh env: unexpected arguments" >&2; exit 2; }
    exec "$PY" -I "$TOOL" env --repo "$REPO" --workspace "$WS" ;;
  demo)
    NAME="demo"
    case "${#ARGS[@]}" in 0) ;; 2) [ "${ARGS[0]}" = "--name" ] || { echo "dev.sh demo: usage: demo [--name NAME]" >&2; exit 2; }; NAME="${ARGS[1]}" ;; *) echo "dev.sh demo: usage: demo [--name NAME]" >&2; exit 2 ;; esac
    W="$(tool check-workspace --repo "$REPO" --workspace "$WS" --mode owned)" || exit 1
    [ -x "$W/venv/bin/python" ] || die "no venv in $W; run: dev.sh setup"
    exec env PYTHONPATH="$REPO:$REPO/applications/refund_desk" REFUND_DESK_STACK_ROOT="$W/stack" "$W/venv/bin/python" "$TOOL" demo --repo "$REPO" --workspace "$W" --name "$NAME" ;;
  evidence)
    [ ${#ARGS[@]} -eq 2 ] && [ "${ARGS[0]}" = "--state" ] || { echo "dev.sh evidence: usage: evidence --state DIR" >&2; exit 2; }
    exec "$PY" -I "$TOOL" evidence --repo "$REPO" --workspace "$WS" --state "${ARGS[1]}" ;;
  cleanup)
    exec "$PY" -I "$TOOL" cleanup --repo "$REPO" --workspace "$WS" "${ARGS[@]}" ;;
  *) echo "dev.sh: unknown command: $CMD" >&2; usage >&2; exit 2 ;;
esac
