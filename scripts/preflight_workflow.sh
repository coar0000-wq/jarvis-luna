#!/usr/bin/env bash
# Only exit 2 from preflight.py is advisory. Tests and I/O failures are fatal.
set -euo pipefail
log_dir="${RUNNER_TEMP:-/tmp}/jarvis-preflight"
keys=(preflight mermaid self_improve replay team_learning shortlist graph_check)

run_check() {
  local key="$1" policy="$2"
  shift 2
  local log="$log_dir/$key.txt" raw tee_rc log_ok=0
  local -a statuses
  # GitHub's bash -e -o pipefail must not abort before PIPESTATUS is saved.
  set +e
  "$@" 2>&1 | tee "$log"
  statuses=("${PIPESTATUS[@]}")
  set -e
  raw="${statuses[0]}"
  tee_rc="${statuses[1]}"
  [[ -s "$log" ]] && log_ok=1
  printf '%s_rc=%s\n%s_tee_rc=%s\n%s_log_ok=%s\n' \
    "$key" "$raw" "$key" "$tee_rc" "$key" "$log_ok" >> "$GITHUB_OUTPUT"
  printf 'exit=%s tee=%s output_present=%s\n' "$raw" "$tee_rc" "$log_ok" > "$log_dir/$key.status"
  if [[ "$tee_rc" != 0 || "$log_ok" != 1 ]]; then
    aggregate=1
  elif [[ "$raw" != 0 && ! ( "$policy" == warnings && "$raw" == 2 ) ]]; then
    aggregate=1
  fi
}

case "${1:-}" in
  preflight|graph)
    : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
    mkdir -p "$log_dir"
    aggregate=0
    if [[ "$1" == preflight ]]; then
      run_check preflight warnings python scripts/preflight.py
    else
      # Never lose an early failure, and never skip later checks because of it.
      run_check mermaid strict python scripts/test_build_artifact_graph_mermaid.py
      run_check self_improve strict python scripts/test_self_improve.py
      run_check replay strict python scripts/test_self_improve_replay.py
      run_check team_learning strict python scripts/test_team_learning.py
      run_check shortlist strict python scripts/test_shopify_shortlist_guard.py
      run_check graph_check strict python scripts/build_artifact_graph.py --check
    fi
    printf 'rc=%s\ncompleted=true\n' "$aggregate" >> "$GITHUB_OUTPUT"
    exit "$aggregate"
    ;;
  summary)
    : "${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY is required}"
    missing=0
    {
      printf '### Preflight and artifact graph checks\n\n'
      printf 'Workflow regression tests: %s\n\n' "${REGRESSION_OUTCOME:-MISSING}"
      printf 'Operational repair tests: %s\n\n' "${REPAIR_OUTCOME:-MISSING}"
      if [[ -z "${REPAIR_OUTCOME:-}" ]]; then missing=1; fi
      for key in "${keys[@]}"; do
        printf '#### %s\n\n' "$key"
        if [[ -s "$log_dir/$key.status" ]]; then
          cat "$log_dir/$key.status"
        else
          printf 'NOT RUN / MISSING STATUS\n'
          missing=1
        fi
        printf '\n~~~text\n'
        if [[ -s "$log_dir/$key.txt" ]]; then
          cat "$log_dir/$key.txt"
        else
          printf 'NOT RUN / MISSING OUTPUT\n'
          missing=1
        fi
        printf '\n~~~\n\n'
      done
    } >> "$GITHUB_STEP_SUMMARY"
    exit "$missing"
    ;;
  gate)
    # Empty, skipped, cancelled, and unexpected outputs are not passes.
    if [[ "${REGRESSION_OUTCOME:-}" == success &&
          "${REPAIR_OUTCOME:-}" == success &&
          "${PF_OUTCOME:-}" == success && "${PF_COMPLETED:-}" == true &&
          "${PF_RC:-}" == 0 && "${PF_TEE_RC:-}" == 0 && "${PF_LOG_OK:-}" == 1 &&
          ( "${PF_RAW_RC:-}" == 0 || "${PF_RAW_RC:-}" == 2 ) &&
          "${GRAPH_OUTCOME:-}" == success && "${GRAPH_COMPLETED:-}" == true &&
          "${GRAPH_RC:-}" == 0 && "${SUMMARY_OUTCOME:-}" == success ]]; then
      echo 'PASS: all required checks completed (preflight warnings are advisory).'
    else
      echo 'FAIL: failed, skipped, missing checks or missing output. See summary.'
      exit 1
    fi
    ;;
  *) echo 'Usage: preflight_workflow.sh {preflight|graph|summary|gate}' >&2; exit 64 ;;
esac
