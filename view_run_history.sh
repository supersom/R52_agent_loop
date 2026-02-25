#!/usr/bin/env bash

jq -r '.[] |
  "=== Text Fields (Attempt \(.attempt)) ===
  prompt:
  \(.prompt)

  diff:
  \(.diff)

  === generated_code ===
  \(.generated_code)
  "' run_history.json
