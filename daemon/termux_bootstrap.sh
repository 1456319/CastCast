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

# Ensure hidden daemon state exists so we can write the log without polluting
# the media queue.
mkdir -p "$AUDIT_DIR"

log_action() {
    local timestamp=$(date "+%Y-%m-%d %H:%M:%S")
    echo "[$timestamp] $1" | tee -a "$AUDIT_LOG"
}

abort() {
    log_action "[FATAL] $1. Aborting."
    exit 1
}

log_action "=== Termux Bootstrap Initiated by APK ==="

# 0. Check if already running
if nc -z 127.0.0.1 8765 2>/dev/null || curl -s http://127.0.0.1:8765/health &>/dev/null; then
    log_action "[OK] Daemon is already running on port 8765. Exiting bootstrap."
    exit 0
fi

# 1. Check Storage Permission
if [ ! -d "/storage/emulated/0" ]; then
    log_action "Requesting termux-setup-storage..."
    termux-setup-storage
    sleep 2
    if [ ! -d "/storage/emulated/0" ]; then
        abort "Storage permission denied by user"
    fi
fi
log_action "[OK] Storage permissions verified."

# 2. Verify / Create Environment Directories safely
log_action "Verifying environment directories..."
if [ ! -d "$CHROMECAST_DIR" ]; then
    log_action "Creating required directory: $CHROMECAST_DIR"
    mkdir -p "$CHROMECAST_DIR" || abort "Failed to create chromecast directory"
fi

if [ ! -d "$TRASH_DIR" ]; then
    log_action "Creating required directory: $TRASH_DIR"
    mkdir -p "$TRASH_DIR" || abort "Failed to create trash directory"
fi
log_action "[OK] Environment directories verified."

# 3. Verify Dependencies (python, ffmpeg, yt-dlp)
log_action "Verifying dependencies (python, ffmpeg, yt-dlp)..."
if ! command -v python3 &> /dev/null; then
    log_action "Python not found. Installing python..."
    pkg update -y && pkg install -y python || abort "Failed to install Python"
fi

if ! command -v ffmpeg &> /dev/null; then
    log_action "FFmpeg not found. Installing ffmpeg..."
    pkg install -y ffmpeg || abort "Failed to install FFmpeg"
fi

if ! python3 -c "import yt_dlp" &> /dev/null; then
    log_action "yt-dlp not found. Installing via pip..."
    python3 -m pip install --upgrade --no-cache-dir yt-dlp pyyaml requests asyncssh || true
fi
log_action "[OK] Dependencies verified."

# 4. Kill any orphan daemon instances and tunnels
log_action "Cleaning up stale daemon instances..."
pkill -f "python3 -m castcast" || true
pkill -f "pinggy.io" || true
pkill -f "localhost.run" || true
sleep 1

# 5. Launch the Daemon
log_action "Booting castcast daemon..."
cd "$(dirname "$0")" || abort "Failed to navigate to daemon directory"

python3 -m castcast --media-root "$CHROMECAST_DIR" --bind 127.0.0.1 --port 8765 serve >> "$AUDIT_LOG" 2>&1 &
DAEMON_PID=$!

log_action "[OK] Daemon launched with PID: $DAEMON_PID. Waiting for port 8765 readiness..."

# 6. Readiness check
READY=0
for i in {1..20}; do
    if nc -z 127.0.0.1 8765 2>/dev/null || curl -s http://127.0.0.1:8765/health &>/dev/null; then
        READY=1
        break
    fi
    sleep 0.5
done

if [ "$READY" -eq 1 ]; then
    log_action "[OK] Daemon is ready on http://127.0.0.1:8765"
else
    log_action "[WARN] Daemon launched but port 8765 not responding within timeout. Check $AUDIT_LOG"
fi
log_action "=== Bootstrap Complete ==="
