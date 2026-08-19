#!/data/data/com.termux/files/usr/bin/bash

# =======================================================================
# VideoQualityCheckerApp - Termux Bootstrap & Audit Script
# =======================================================================
# This script is called automatically by the Capacitor APK via an Android
# Intent (com.termux.app.RunCommandService). It ensures the environment
# is safely established and logs every action to a user-readable audit log.
#
# Trust & Transparency:
# If a critical failure occurs, the script will ABORT rather than taking
# arbitrary destructive actions.
# =======================================================================

# Canonical user-visible queue; /sdcard/Download/Chromecast is its Android
# alias. Keep this case synchronized with CastService.DEFAULT_MEDIA_ROOT.
CHROMECAST_DIR="/storage/emulated/0/Download/VideoQualityCheckerApp/Chromecast"
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

# 3. Verify Dependencies
log_action "Verifying dependencies (python, ffmpeg)..."
if ! command -v python3 &> /dev/null; then
    log_action "Python not found. Installing python..."
    pkg install -y python || abort "Failed to install Python"
fi

if ! command -v ssh &> /dev/null; then
    log_action "OpenSSH not found. Installing openssh for DRM tunneling..."
    pkg install -y openssh || abort "Failed to install OpenSSH"
fi

if ! command -v ffmpeg &> /dev/null; then
    log_action "FFmpeg not found. Installing ffmpeg..."
    pkg install -y ffmpeg || abort "Failed to install FFmpeg"
fi

if ! command -v node &> /dev/null; then
    log_action "NodeJS not found. Installing nodejs..."
    pkg install -y nodejs || abort "Failed to install NodeJS"
fi
log_action "[OK] Dependencies verified."

# 4. Kill any old daemon instances and orphan SSH tunnels
log_action "Cleaning up old daemon instances..."
pkill -f "python3 -m castcast" || true
pkill -f "pinggy.io" || true
sleep 1

# 5. Launch the Daemon
log_action "Booting castcast daemon..."
cd "$(dirname "$0")" || abort "Failed to navigate to daemon directory"

# Run the daemon in the background and pipe output to the audit log
python3 -m castcast --media-root "$CHROMECAST_DIR" serve >> "$AUDIT_LOG" 2>&1 &
DAEMON_PID=$!

log_action "[OK] Daemon launched with PID: $DAEMON_PID"
log_action "=== Bootstrap Complete ==="
