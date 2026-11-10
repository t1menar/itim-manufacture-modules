# deploy/lib/log.sh — animated deployment logs (bash 4+).
# shellcheck shell=bash
# Usage: source this file after setting DEPLOY_ROOT and optionally MF_LOG_FILE.

: "${DEPLOY_ROOT:?DEPLOY_ROOT must be set before sourcing log.sh}"

_MF_COLOR=1
_MF_ANIM=1
_MF_VERBOSE=0
_MF_STEP=0
_MF_STEPS=0
_MF_SPIN_PID=""
_MF_STEP_START=0
_MF_RUN_START=0

_mf_isatty() {
  [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]] && [[ "${CI:-}" != "1" ]] && [[ "${TERM:-dumb}" != "dumb" ]]
}

mf_log_init() {
  local total="${1:-0}"
  _MF_STEPS="$total"
  _MF_STEP=0
  _MF_RUN_START=$(date +%s)
  if ! _mf_isatty; then
    _MF_COLOR=0
    _MF_ANIM=0
  fi
  if [[ "${MF_VERBOSE:-0}" == "1" ]] || [[ "${1:-}" == "--verbose-flag" ]]; then
    _MF_VERBOSE=1
  fi
  mkdir -p "${DEPLOY_ROOT}/.logs"
  if [[ -z "${MF_LOG_FILE:-}" ]]; then
    MF_LOG_FILE="${DEPLOY_ROOT}/.logs/$(date +%Y%m%d-%H%M%S).log"
  fi
  : >"$MF_LOG_FILE"
  export MF_LOG_FILE
  trap '_mf_on_exit' EXIT
  trap '_mf_on_interrupt' INT TERM
}

mf_log_set_verbose() { _MF_VERBOSE=1; }
mf_log_disable_anim() { _MF_ANIM=0; _MF_COLOR=0; }

_mf_c() {
  local code="$1"; shift
  if [[ "$_MF_COLOR" == "1" ]]; then
    printf '\033[%sm%s\033[0m' "$code" "$*"
  else
    printf '%s' "$*"
  fi
}

_mf_ts() { date '+%H:%M:%S'; }

_mf_elapsed() {
  local start="${1:-$_MF_RUN_START}"
  local now
  now=$(date +%s)
  printf '%dm%02ds' $(((now - start) / 60)) $(((now - start) % 60))
}

_mf_file() {
  # Append plain text to log file (no ANSI).
  printf '%s\n' "$*" >>"$MF_LOG_FILE"
}

mf_banner() {
  local title="${1:-Manufacture local stack}"
  local line
  line=$(printf '═%.0s' {1..56})
  _mf_file "=== $title ==="
  if [[ "$_MF_ANIM" == "1" ]]; then
    printf '\n%s\n' "$(_mf_c 36 "$line")"
    printf '  %s\n' "$(_mf_c 1 "$title")"
    printf '%s\n\n' "$(_mf_c 36 "$line")"
  else
    printf '\n== %s ==\n\n' "$title"
  fi
}

mf_info() {
  local msg="$*"
  _mf_file "[INFO] $msg"
  printf '%s %s %s\n' "$(_mf_c 90 "$(_mf_ts)")" "$(_mf_c 36 "ℹ")" "$msg"
}

mf_warn() {
  local msg="$*"
  _mf_file "[WARN] $msg"
  printf '%s %s %s\n' "$(_mf_c 90 "$(_mf_ts)")" "$(_mf_c 33 "⚠")" "$msg"
}

mf_err() {
  local msg="$*"
  _mf_file "[ERR] $msg"
  printf '%s %s %s\n' "$(_mf_c 90 "$(_mf_ts)")" "$(_mf_c 31 "✖")" "$msg" >&2
}

mf_ok() {
  local msg="$*"
  _mf_file "[OK] $msg"
  printf '%s %s %s\n' "$(_mf_c 90 "$(_mf_ts)")" "$(_mf_c 32 "✔")" "$msg"
}

_mf_stop_spinner() {
  if [[ -n "${_MF_SPIN_PID:-}" ]] && kill -0 "$_MF_SPIN_PID" 2>/dev/null; then
    kill "$_MF_SPIN_PID" 2>/dev/null || true
    wait "$_MF_SPIN_PID" 2>/dev/null || true
  fi
  _MF_SPIN_PID=""
  if [[ "$_MF_ANIM" == "1" ]]; then
    printf '\r\033[K' >&2
  fi
}

_mf_spinner_loop() {
  local msg="$1"
  local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
  local i=0
  local start
  start=$(date +%s)
  while true; do
    local elapsed
    elapsed=$(_mf_elapsed "$start")
    printf '\r%s %s %s  %s' "$(_mf_c 90 "$(_mf_ts)")" "$(_mf_c 36 "${frames[i]}")" "$msg" "$(_mf_c 90 "$elapsed")" >&2
    i=$(((i + 1) % ${#frames[@]}))
    sleep 0.08
  done
}

mf_step_begin() {
  local msg="$1"
  _mf_stop_spinner
  _MF_STEP=$((_MF_STEP + 1))
  _MF_STEP_START=$(date +%s)
  local prefix
  if [[ "$_MF_STEPS" -gt 0 ]]; then
    prefix="[$(_mf_c 1 "${_MF_STEP}/${_MF_STEPS}")]"
  else
    prefix="[$(_mf_c 1 "${_MF_STEP}")]"
  fi
  _mf_file "----- STEP ${_MF_STEP}: $msg -----"
  printf '%s %s %s\n' "$(_mf_c 90 "$(_mf_ts)")" "$prefix" "$msg"
  if [[ "$_MF_ANIM" == "1" ]] && [[ "$_MF_VERBOSE" != "1" ]]; then
    _mf_spinner_loop "$msg" &
    _MF_SPIN_PID=$!
  fi
}

mf_step_end() {
  local status="${1:-ok}" # ok|fail|skip
  local detail="${2:-}"
  _mf_stop_spinner
  local dur
  dur=$(_mf_elapsed "$_MF_STEP_START")
  case "$status" in
    ok)
      _mf_file "[STEP OK] (${dur}) ${detail}"
      printf '%s %s %s %s\n' "$(_mf_c 90 "$(_mf_ts)")" "$(_mf_c 32 "✔")" "${detail:-done}" "$(_mf_c 90 "$dur")"
      ;;
    skip)
      _mf_file "[STEP SKIP] (${dur}) ${detail}"
      printf '%s %s %s %s\n' "$(_mf_c 90 "$(_mf_ts)")" "$(_mf_c 33 "↷")" "${detail:-skipped}" "$(_mf_c 90 "$dur")"
      ;;
    *)
      _mf_file "[STEP FAIL] (${dur}) ${detail}"
      printf '%s %s %s %s\n' "$(_mf_c 90 "$(_mf_ts)")" "$(_mf_c 31 "✖")" "${detail:-failed}" "$(_mf_c 90 "$dur")" >&2
      ;;
  esac
}

mf_run() {
  # Run command; capture to step log; on failure dump tail.
  local step_log
  step_log=$(mktemp "${TMPDIR:-/tmp}/mf-step.XXXXXX")
  local rc=0
  if [[ "$_MF_VERBOSE" == "1" ]]; then
    # shellcheck disable=SC2094
    "$@" 2>&1 | tee -a "$MF_LOG_FILE" | tee "$step_log" || rc=$?
  else
    "$@" >>"$step_log" 2>&1 || rc=$?
    cat "$step_log" >>"$MF_LOG_FILE"
  fi
  if [[ "$rc" -ne 0 ]]; then
    _mf_stop_spinner
    mf_err "command failed (exit $rc): $*"
    mf_err "log file: $MF_LOG_FILE"
    mf_err "--- last 40 lines ---"
    tail -n 40 "$step_log" | while IFS= read -r line; do
      printf '  %s\n' "$line" >&2
    done
    rm -f "$step_log"
    return "$rc"
  fi
  rm -f "$step_log"
  return 0
}

mf_wait_http() {
  # mf_wait_http URL [timeout_s=60] [label]
  local url="$1"
  local timeout="${2:-60}"
  # third arg (label) reserved for callers
  _="${3:-}"
  local start now elapsed
  start=$(date +%s)
  local width=24
  while true; do
    now=$(date +%s)
    elapsed=$((now - start))
    if [[ "$elapsed" -ge "$timeout" ]]; then
      _mf_stop_spinner
      return 1
    fi
    if curl -sf --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    if [[ "$_MF_ANIM" == "1" ]]; then
      local filled=$((elapsed * width / timeout))
      [[ "$filled" -gt "$width" ]] && filled=$width
      local bar empty
      bar=$(printf '█%.0s' $(seq 1 "$filled" 2>/dev/null) 2>/dev/null || true)
      empty=$(printf '░%.0s' $(seq 1 $((width - filled)) 2>/dev/null) 2>/dev/null || true)
      printf '\r%s %s [%s%s] %ss/%ss' "$(_mf_c 90 "$(_mf_ts)")" "$(_mf_c 36 "…")" "$bar" "$empty" "$elapsed" "$timeout" >&2
    fi
    sleep 1
  done
}

mf_table() {
  # mf_table "col1|col2" "a|b" ...
  local row
  for row in "$@"; do
    _mf_file "  $row"
    printf '  %s\n' "$row"
  done
}

mf_summary_footer() {
  local dur
  dur=$(_mf_elapsed "$_MF_RUN_START")
  _mf_file "=== finished in $dur ==="
  printf '\n%s %s\n' "$(_mf_c 32 "✔")" "Готово за $dur  ·  лог: $MF_LOG_FILE"
}

_mf_on_exit() {
  local rc=$?
  _mf_stop_spinner
  if [[ "$rc" -ne 0 ]]; then
    printf '\n' >&2
    mf_err "стек остановлен с кодом $rc · полный лог: ${MF_LOG_FILE:-?}"
  fi
}

_mf_on_interrupt() {
  _mf_stop_spinner
  mf_warn "прервано пользователем"
  exit 130
}
