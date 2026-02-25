#!/usr/bin/env bash

set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROMPT="prompts/prime_sum.txt"

usage() {
  echo "Usage:"
  echo "  $0                                  # active run history for default prompt"
  echo "  $0 <prompt-path>                    # active run history for prompt"
  echo "  $0 <prompt-path> <timestamp>        # specific snapshot by timestamp"
  echo "  $0 <code/<prompt>/<timestamp>>      # specific snapshot directory"
}

resolve_active_prompt_dir() {
  local prompt_name="$1"
  printf '%s\n' "$WORKSPACE/code/$prompt_name"
}

resolve_history_dir() {
  if [[ $# -eq 0 ]]; then
    local prompt_name
    prompt_name="$(basename "$DEFAULT_PROMPT")"
    resolve_active_prompt_dir "$prompt_name"
    return
  fi

  if [[ $# -eq 1 ]]; then
    local arg="$1"

    if [[ "$arg" == "code/"* || "$arg" == */*/* ]]; then
      printf '%s\n' "$WORKSPACE/${arg#./}"
      return
    fi

    local prompt_name
    prompt_name="$(basename "$arg")"
    resolve_active_prompt_dir "$prompt_name"
    return
  fi

  if [[ $# -eq 2 ]]; then
    local prompt_name
    prompt_name="$(basename "$1")"
    printf '%s\n' "$WORKSPACE/code/$prompt_name/$2"
    return
  fi

  usage >&2
  exit 1
}

HISTORY_DIR="$(resolve_history_dir "$@")"
HISTORY_FILE="$HISTORY_DIR/run_history.json"

if [[ ! -f "$HISTORY_FILE" ]]; then
  echo "run_history.json not found: $HISTORY_FILE" >&2
  exit 1
fi

echo "Reading run history from: $HISTORY_FILE"

jq -r '.[] |
  "=== Text Fields (Attempt \(.attempt)) ===
  prompt:
  \(.prompt)

  diff:
  \(.diff)

  === generated_code ===
  \(.generated_code)
  "' "$HISTORY_FILE"
