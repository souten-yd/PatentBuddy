#!/bin/sh
# QTS service script: start | stop | status | restart
set -u
name=QnapLibrary
config=/etc/config/qpkg.conf
if [ -x /sbin/getcfg ] && [ -f "$config" ]; then
    root=$(/sbin/getcfg "$name" Install_Path -d "" -f "$config")
else
    root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
fi
[ -n "$root" ] || { echo 'QPKG installation path missing' >&2; exit 1; }
data_dir=${QNAPLIBRARY_DATA:-"$(dirname "$root")/QnapLibrary-data"}
pidfile="$data_dir/qnaplibrary.pid"
# Memory-only logging by default (low HDD I/O). Set QNAPLIBRARY_LOG_MODE=disk to capture stderr.
case "${QNAPLIBRARY_LOG_MODE:-memory}" in
    disk) log_output="$data_dir/qnaplibrary.log" ;;
    *) log_output=/dev/null ;;
esac

owned_pid() {
    pid=$(cat "$pidfile" 2>/dev/null || true)
    case "$pid" in ''|*[!0-9]*) return 1 ;; esac
    [ -r "/proc/$pid/cmdline" ] || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "qnaplibrary-runner $root" || return 1
    echo "$pid"
}

case "${1:-}" in
    start)
        if [ -x /sbin/getcfg ] && [ -f "$config" ]; then
            enabled=$(/sbin/getcfg "$name" Enable -u -d FALSE -f "$config")
            [ "$enabled" = TRUE ] || { echo "$name is disabled" >&2; exit 1; }
        fi
        if owned_pid >/dev/null; then echo "$name is already running"; exit 0; fi
        umask 077
        # QTS may start QPKGs before volumes and the Python3 QPKG are ready: wait (max 180 s).
        elapsed=0
        while :; do
            if [ -d "$(dirname "$data_dir")" ] && python=$(/bin/sh "$root/python3-path" 2>/dev/null); then
                break
            fi
            [ "$elapsed" -ge 180 ] && { echo "$name: volume or Python3 not ready after ${elapsed}s" >&2; exit 1; }
            sleep 2; elapsed=$((elapsed + 2))
        done
        mkdir -p "$data_dir"
        # Runner loop: exit code 75 = restart requested by the app (e.g. after settings change).
        (
            exec /bin/sh -c '
                root="$1"; python="$2"; data="$3"
                cd "$root" || exit 1   # python -m imports from the working directory first
                while :; do
                    QNAPLIBRARY_INSTALL_MODE=qpkg QNAPLIBRARY_INSTALL_ROOT="$root" PYTHONPATH="$root" \
                        "$python" -B -m qnaplibrary --data "$data"
                    code=$?
                    [ "$code" -eq 75 ] || exit "$code"
                    sleep 1
                done' qnaplibrary-runner "$root" "$python" "$data_dir"
        ) < /dev/null > "$log_output" 2>&1 &
        echo $! > "$pidfile"
        tries=0
        while [ "$tries" -lt 20 ]; do
            if owned_pid >/dev/null; then echo "$name started"; exit 0; fi
            sleep 1; tries=$((tries + 1))
        done
        echo "$name did not start; run with QNAPLIBRARY_LOG_MODE=disk to see errors" >&2
        exit 1
        ;;
    stop)
        pid=$(owned_pid) || { echo "$name is not running"; rm -f "$pidfile"; exit 0; }
        # stop the runner loop and its python child
        for s in /proc/[0-9]*/status; do
            ppid=$(awk '/^PPid:/ {print $2}' "$s" 2>/dev/null)
            [ "$ppid" = "$pid" ] && kill -TERM "$(basename "$(dirname "$s")")" 2>/dev/null
        done
        sleep 1
        kill -TERM "$pid" 2>/dev/null || true
        n=0
        while [ -d "/proc/$pid" ] && [ "$n" -lt 15 ]; do sleep 1; n=$((n + 1)); done
        [ -d "/proc/$pid" ] && kill -KILL "$pid" 2>/dev/null
        rm -f "$pidfile"
        echo "$name stopped"
        ;;
    status)
        if owned_pid >/dev/null; then echo "$name is running"; exit 0; fi
        echo "$name is stopped"; exit 1
        ;;
    restart)
        "$0" stop
        "$0" start
        ;;
    *) echo "Usage: $0 {start|stop|status|restart}" >&2; exit 2 ;;
esac
