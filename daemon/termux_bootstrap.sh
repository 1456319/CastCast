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

# Canonical user-visible queue; /sdcard/Download/Chromecast is its Android
# alias lives under Download/CastCast. Keep this case synchronized with CastService.DEFAULT_MEDIA_ROOT.
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
    if [ -f "$AUDIT_LOG" ] && [ $(wc -c < "$AUDIT_LOG" 2>/dev/null || echo 0) -gt 2097152 ]; then
        mv -f "$AUDIT_LOG" "$AUDIT_LOG.1" 2>/dev/null || true
    fi
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

for dependency in lsof flock; do
    if ! command -v "$dependency" >/dev/null; then
        pkg install -y lsof util-linux || abort "Failed to install daemon lifecycle tools"
    fi
done

# 4. Run the APK's exact bundled daemon in the Termux service job.
# Do not git-pull here: updating Python independently of the APK breaks the API
# contract. Do not pkill SSH or arbitrary Python processes.
cd "$(dirname "$0")" || abort "Failed to navigate to bundled daemon directory"
python3 -m castcast server kill >> "$AUDIT_LOG" 2>&1 || abort "Existing listener could not be verified or stopped"

mkdir -p "$HOME/.config/castcast"
exec 9>"$HOME/.config/castcast/daemon.lock"
flock -w 10 9 || abort "Previous CastCast service job has not exited"

# Keep Termux's background job alive for the daemon lifetime. Its wake lock
# belongs to Termux, so closing the controller activity does not release it.
termux-wake-lock || abort "Failed to acquire the Termux wake lock"
trap 'termux-wake-unlock' EXIT
log_action "Starting bundled daemon from $PWD"
python3 -m castcast --media-root "$CHROMECAST_DIR" serve --quiet >> "$AUDIT_LOG" 2>&1
DAEMON_RESULT=$?
log_action "Daemon exited with status $DAEMON_RESULT"
exit "$DAEMON_RESULT"
