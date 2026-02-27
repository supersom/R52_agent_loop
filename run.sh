#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./run longtest <prompt> <exp>

Examples:
  ./run longtest xor_checksum "XOR: 08"
  ./run longtest prompts/print_hex32.md "HEX: DEADBEEF"
EOF
}

resolve_prompt_file() {
  local input="$1"

  if [[ -f "$input" ]]; then
    printf '%s\n' "$input"
    return
  fi

  if [[ -f "prompts/$input" ]]; then
    printf '%s\n' "prompts/$input"
    return
  fi

  if [[ -f "prompts/$input.md" ]]; then
    printf '%s\n' "prompts/$input.md"
    return
  fi

  if [[ -f "prompts/$input.txt" ]]; then
    printf '%s\n' "prompts/$input.txt"
    return
  fi

  return 1
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

subcommand="$1"
shift

case "$subcommand" in
  longtest)
    if [[ $# -ne 2 ]]; then
      usage
      exit 1
    fi

    prompt_arg="$1"
    exp="$2"

    if ! prompt_file="$(resolve_prompt_file "$prompt_arg")"; then
      echo "Prompt file not found for: $prompt_arg" >&2
      exit 1
    fi

    prompt_name="$(basename "$prompt_file")"
    prompt="${prompt_name%.*}"

    out="code/${prompt}/orchestrator_batch_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$out"
    ok=0

    for i in $(seq 1 10); do
      n="$(printf '%02d' "$i")"
      echo "Run $n/10"

      python orchestrator.py -y --toolchain ds5 --prompt "$prompt_file" --expected "$exp" >"$out/run_${n}.log" 2>&1

      hist="code/${prompt}/run_history.json"
      if [[ -f "$hist" ]]; then
        cp "$hist" "$out/run_${n}_run_history.json"
        if jq -e '.[-1].attempt_result=="success"' "$hist" >/dev/null; then
          ok=$((ok+1))
          echo "success"
        else
          echo "fail"
        fi
      else
        echo "fail (no run_history.json)"
      fi
    done

    echo "Successes: $ok/10"
    echo "Saved logs + run histories in: $out"
    ;;

  *)
    echo "Unknown subcommand: $subcommand" >&2
    usage
    exit 1
    ;;
esac
