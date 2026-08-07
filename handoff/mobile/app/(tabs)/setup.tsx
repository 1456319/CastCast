/**
 * Setup / readiness screen.
 *
 * This is the screen you land on when nothing works yet. Its whole job is to
 * turn "casting doesn't work" into one specific sentence and one command you
 * can paste into Termux.
 *
 * Design rules, in order of importance:
 *
 * 1. Never guess. If the daemon is unreachable we genuinely cannot know
 *    whether ffmpeg is installed, so those rows render `?` rather than red.
 *    Inventing a red row here would be the same mistake as the mock
 *    diagnostics that were previously (correctly) removed from this app.
 * 2. Dependency order. Rows are listed so the first non-green row is the real
 *    cause. Fixing rows out of order wastes the user's time.
 * 3. Every failure carries the literal command. No paraphrasing, no "install
 *    ffmpeg" prose -- the exact string, with a copy button, because a
 *    mistyped flag is exactly the class of bug that produced B1 in the plan.
 *
 * The app never launches the daemon. That is a deliberate scope decision: it
 * would require the Termux RUN_COMMAND permission and a `<queries>` manifest
 * entry, and it depends on the user having set `allow-external-apps=true` in
 * ~/.termux/termux.properties, which an APK cannot do on their behalf. Keeping
 * to detect-and-verify means the shipped manifest holds at exactly INTERNET +
 * ACCESS_NETWORK_STATE, which is what docs/PACKAGING.md claims.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';

import { DaemonUnreachable, getHealth, type Health, type HealthCheck } from '../../lib/daemon';

const PKG_INSTALL = 'pkg install python ffmpeg';
const SETUP_STORAGE = 'termux-setup-storage';
const FALLBACK_SERVE =
  'python -m castcast --media-root /storage/emulated/0/Download/Chromecast serve';

type RowState = 'pass' | 'fail' | 'warn' | 'unknown';

interface Row {
  key: string;
  label: string;
  state: RowState;
  detail: string;
  remedy?: string;
}

function stateOf(check: HealthCheck): RowState {
  if (check.ok === true) return 'pass';
  if (check.ok === false) return check.blocking ? 'fail' : 'warn';
  return 'unknown';
}

/**
 * Build the checklist. When `health` is null the daemon did not answer, so
 * every downstream row is genuinely unknown -- not failing.
 */
function buildRows(health: Health | null, unreachable: boolean): Row[] {
  const daemonRow: Row = unreachable
    ? {
        key: 'daemon',
        label: 'Daemon reachable',
        state: 'fail',
        detail: 'nothing is listening on 127.0.0.1:8765',
        remedy: `${PKG_INSTALL}\n${FALLBACK_SERVE}`,
      }
    : {
        key: 'daemon',
        label: 'Daemon reachable',
        state: health ? 'pass' : 'unknown',
        detail: health
          ? `castcast ${health.version} on Python ${health.python}`
          : 'checking...',
      };

  if (!health) {
    return [
      daemonRow,
      {
        key: 'tools',
        label: 'ffmpeg / ffprobe',
        state: 'unknown',
        detail: 'cannot be checked until the daemon responds',
      },
      {
        key: 'storage',
        label: 'Media folder',
        state: 'unknown',
        detail: 'cannot be checked until the daemon responds',
        remedy: SETUP_STORAGE,
      },
      {
        key: 'lan',
        label: 'LAN address',
        state: 'unknown',
        detail: 'cannot be checked until the daemon responds',
      },
    ];
  }

  // The daemon already orders its checks sensibly and attaches remedies, so
  // pass them straight through rather than re-deriving them here. Keeping the
  // remedy strings server-side means they stay correct when the CLI changes.
  return [
    daemonRow,
    ...health.checks.map((check) => ({
      key: check.key,
      label: check.label,
      state: stateOf(check),
      detail: check.detail,
      remedy: check.remedy || undefined,
    })),
  ];
}

const MARKS: Record<RowState, { glyph: string; color: string }> = {
  pass: { glyph: '●', color: '#3FB950' },
  fail: { glyph: '●', color: '#F85149' },
  warn: { glyph: '●', color: '#D29922' },
  unknown: { glyph: '?', color: '#6E7681' },
};

function CheckRow({ row }: { row: Row }) {
  const [copied, setCopied] = useState(false);
  const mark = MARKS[row.state];

  const copy = useCallback(async () => {
    if (!row.remedy) return;
    await Clipboard.setStringAsync(row.remedy);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [row.remedy]);

  const showRemedy = row.remedy && row.state !== 'pass';

  return (
    <View style={styles.row}>
      <View style={styles.rowHead}>
        <Text style={[styles.mark, { color: mark.color }]}>{mark.glyph}</Text>
        <View style={styles.rowText}>
          <Text style={styles.rowLabel}>{row.label}</Text>
          <Text style={styles.rowDetail}>{row.detail || '—'}</Text>
        </View>
      </View>

      {showRemedy ? (
        <Pressable
          style={({ pressed }) => [styles.remedy, pressed && styles.remedyPressed]}
          onPress={copy}
          accessibilityRole="button"
          accessibilityLabel={`Copy command: ${row.remedy}`}>
          <Text style={styles.remedyText} selectable>
            {row.remedy}
          </Text>
          <Text style={styles.copyHint}>{copied ? 'copied' : 'tap to copy'}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export default function SetupScreen() {
  const [health, setHealth] = useState<Health | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const next = await getHealth();
      setHealth(next);
      setUnreachable(false);
    } catch (err) {
      setHealth(null);
      if (err instanceof DaemonUnreachable) {
        setUnreachable(true);
      } else {
        setUnreachable(false);
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    // Poll while the daemon is down so the screen goes green on its own the
    // moment the user starts it in Termux -- they should not have to come back
    // and pull to refresh.
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  const rows = buildRows(health, unreachable);
  const ready = health?.ready === true;

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor="#8B949E" />}>
      <Text style={styles.title}>Setup</Text>
      <Text style={styles.subtitle}>
        The daemon runs in Termux. This app talks to it over loopback; it never starts it for
        you.
      </Text>

      {loading && !health && !unreachable ? (
        <ActivityIndicator style={styles.spinner} color="#8B949E" />
      ) : null}

      <View style={[styles.banner, ready ? styles.bannerOk : styles.bannerBad]}>
        <Text style={styles.bannerText}>
          {ready
            ? 'Ready to cast.'
            : unreachable
              ? 'Daemon not running.'
              : 'Not ready — see the red rows below.'}
        </Text>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {rows.map((row) => (
        <CheckRow key={row.key} row={row} />
      ))}

      {health?.serve_command ? (
        <View style={styles.footer}>
          <Text style={styles.footerLabel}>Start command</Text>
          <Text style={styles.footerCmd} selectable>
            {health.serve_command}
          </Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#0A0C10' },
  content: { padding: 20, paddingBottom: 48, gap: 12 },
  title: { color: '#E6EDF3', fontSize: 28 },
  subtitle: { color: '#8B949E', marginBottom: 8 },
  spinner: { marginVertical: 16 },

  banner: { borderRadius: 8, padding: 12, marginBottom: 4 },
  bannerOk: { backgroundColor: '#0E2A16', borderColor: '#238636', borderWidth: 1 },
  bannerBad: { backgroundColor: '#2A0F10', borderColor: '#6E2427', borderWidth: 1 },
  bannerText: { color: '#E6EDF3' },

  error: { color: '#F85149' },

  row: {
    backgroundColor: '#10141B',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#1F2630',
    padding: 12,
    gap: 10,
  },
  rowHead: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  mark: { width: 16, textAlign: 'center' },
  rowText: { flex: 1, gap: 2 },
  rowLabel: { color: '#E6EDF3' },
  rowDetail: { color: '#8B949E' },

  remedy: {
    backgroundColor: '#05070A',
    borderRadius: 6,
    borderWidth: 1,
    borderColor: '#1F2630',
    padding: 10,
    gap: 6,
  },
  remedyPressed: { borderColor: '#3FB950' },
  remedyText: { color: '#9FD5A6', fontFamily: 'monospace' },
  copyHint: { color: '#6E7681' },

  footer: { marginTop: 12, gap: 4 },
  footerLabel: { color: '#8B949E' },
  footerCmd: { color: '#9FD5A6', fontFamily: 'monospace' },
});
