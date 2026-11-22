#!/data/data/com.termux/files/usr/bin/bash
# EDITING OF THIS FILE MAY CAUSE CATASTROPHIC APP DESYCHRONIZATION. Reference the directory at at ~/docs/synchronization_map.md to determine what other files must be adjusted in order to ensure absolute synchronization is maintained. This is to ensure that the APK, termux daemon, and chromecast portions of the app are always in synchronous, deterministic states.

# =======================================================================
# CastCast - Termux Bootstrap & Audit Script
# =======================================================================
# This script is called automatically by the Capacitor APK via an Android
# Intent (com.termux.app.RunCommandService). It ensures the environment
# is safely established and logs every action to a user-readable audit log.
#
# Trust & Transparency:
# If a critical failure occurs, the script will ABORT rather than taking
# arbitrary destructive actions.
# =======================================================================

if [ -z "$HOME" ] || [ "$HOME" = "/data" ]; then
    export HOME="/data/data/com.termux/files/home"
fi
export PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
export PATH="$PREFIX/bin:$PREFIX/bin/applets:$PATH"
export LD_LIBRARY_PATH="$PREFIX/lib:$LD_LIBRARY_PATH"

# Canonical user-visible queue; /sdcard/Download/Chromecast is its Android
# alias. Keep this case synchronized with CastService.DEFAULT_MEDIA_ROOT.
CHROMECAST_DIR="/storage/emulated/0/Download/CastCast/Chromecast"
TRASH_DIR="$CHROMECAST_DIR/trash"
# DEBUG-ONLY: runtime diagnostics are kept out of the visible queue.
AUDIT_DIR="$CHROMECAST_DIR/.castcast"
AUDIT_LOG="$AUDIT_DIR/audit.log"
export CASTCAST_AUDIT_LOG="$AUDIT_LOG"

# Test actual access as Termux before trying package installation.
if ! mkdir -p "$AUDIT_DIR" "$TRASH_DIR" || ! touch "$AUDIT_LOG"; then
    echo "[FATAL] Termux cannot write to $CHROMECAST_DIR. Allow Termux file access in Android Settings and retry."
    exit 1
fi

log_action() {
    local timestamp=$(date "+%Y-%m-%d %H:%M:%S")
    echo "[$timestamp] $1" | tee -a "$AUDIT_LOG"
}

abort() {
    log_action "[FATAL] $1. Aborting."
    exit 1
}

package_failure() {
    tail -n 12 "$AUDIT_LOG"
    abort "$1"
}

log_action "[OK] Termux can write to the CastCast media folder"

packages=()
command -v python3 >/dev/null || packages+=(python)
command -v ssh >/dev/null || packages+=(openssh)
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
    packages+=(ffmpeg)
fi
if [ "${#packages[@]}" -gt 0 ]; then
    log_action "Installing Termux packages: ${packages[*]}"
    pkg update >> "$AUDIT_LOG" 2>&1 || package_failure "Could not refresh Termux packages. Check your connection or Termux repository settings and retry"
    pkg install -y "${packages[@]}" >> "$AUDIT_LOG" 2>&1 || package_failure "Could not install ${packages[*]}. Check Termux package output in $AUDIT_LOG"
fi
for tool in python3 ssh ffmpeg ffprobe; do
    command -v "$tool" >/dev/null || abort "$tool is still missing after installation"
done

if ! command -v yt-dlp >/dev/null; then
    log_action "Installing yt-dlp for supported web links"
    if ! { python3 -m pip --version || pkg install -y python-pip; } >> "$AUDIT_LOG" 2>&1 ||
        ! python3 -m pip install yt-dlp >> "$AUDIT_LOG" 2>&1; then
        log_action "[WARN] Could not install yt-dlp. Local casting can still be set up"
    fi
fi

cd "$(dirname "$0")" || abort "Could not enter the bundled daemon directory"
log_action "Starting the CastCast daemon"
python3 -m castcast --media-root "$CHROMECAST_DIR" serve --api-host 127.0.0.1 --api-port 8765 --if-running exit \
    </dev/null >> "$AUDIT_LOG" 2>&1 &

# The process can fail after it is spawned. Confirm the CastCast API responds.
if ! python3 - <<'PY'
import json
import time
import urllib.request

deadline = time.monotonic() + 25
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/", timeout=1) as response:
            if json.load(response).get("service") == "castcast":
                raise SystemExit(0)
    except (OSError, ValueError, AttributeError):
        pass
    time.sleep(1)
raise SystemExit(1)
PY
then
    abort "The daemon did not answer on port 8765. See $AUDIT_LOG"
fi
log_action "[OK] The CastCast daemon is responding"
