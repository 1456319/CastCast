"""Entry point + a small CLI.

    python -m castcast serve
    python -m castcast devices
    python -m castcast check /storage/emulated/0/Download/Chromecast/movie.mkv
    python -m castcast prepare <file>
    python -m castcast cast <file> --host 192.168.1.50
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

from .api import API_PORT, ApiServer
from .service import CastService

DEFAULT_CONFIG_PATH = "~/.config/castcast/config.json"

DEFAULT_CONFIG = {
    "media_roots": ["/storage/emulated/0/Download/Chromecast"],
    "work_dir": None,
    "static_host": None,
    "static_port": 8009,
    "auto_connect_host": None,
    "media_port": 0,
    "api_host": "127.0.0.1",
    "api_port": API_PORT,
    "device_auth": False,
    "prefer_fmp4": False,
    "avr_passthrough": False,
}


def load_config(path: str) -> dict:
    config = dict(DEFAULT_CONFIG)
    full = os.path.expanduser(path)
    if os.path.exists(full):
        try:
            with open(full, "r", encoding="utf-8") as fh:
                config.update(json.load(fh) or {})
        except (OSError, json.JSONDecodeError) as exc:
            print(f"warning: could not read {full}: {exc}", file=sys.stderr)
    return config


def _tail_logs(service: CastService) -> None:
    seen = 0
    while True:
        for line in service.log_buffer.recent(since=seen):
            seen = line["seq"]
            stamp = time.strftime("%H:%M:%S", time.localtime(line["ts"]))
            print(f"{stamp} [{line['level']}] {line['message']}", flush=True)
        time.sleep(0.25)


def _print_report(report: dict) -> int:
    if report.get("tools_missing"):
        print(f"unknown: {report['warning']}", file=sys.stderr)
        return 2
    if report.get("error") and not report.get("media"):
        print(f"error: {report['error']}", file=sys.stderr)
        return 1

    media = report.get("media") or {}
    verdict = report.get("verdict") or {}
    video = (media.get("video") or [None])[0]
    audio = (media.get("audio") or [None])[0]

    print(f"file       {media.get('path')}")
    print(f"container  {media.get('container')}  ({media.get('format_long')})")
    if video:
        print(f"video      {video['codec']} {video['profile']} L{video.get('level')} "
              f"{video['width']}x{video['height']} @{video['fps']:g}fps "
              f"{video['bit_depth']}-bit {video['hdr_format']}")
    if audio:
        print(f"audio      {audio['codec']} {audio['channels']}ch "
              f"{audio.get('channel_layout')} {audio.get('bitrate_kbps')}kbps")

    print()
    mark = "OK " if verdict.get("castable") and not verdict.get("needs_processing") else "!! "
    print(f"{mark}{verdict.get('summary')}")
    print(f"   true 4K on the Ultra: {'yes' if verdict.get('will_be_4k') else 'no'}")
    print()

    for issue in verdict.get("issues") or []:
        print(f"  [{issue['severity']}] {issue['message']}")
        if issue.get("remedy"):
            print(f"            -> {issue['remedy']}")

    plan = report.get("plan")
    if plan:
        print()
        print("suggested conversion:")
        print(f"  {plan['description']}  (~{plan['estimated']})")
        print(f"  $ {plan['shell_command']}")
    if report.get("prepared_path"):
        print(f"\nalready converted: {report['prepared_path']}")
    return 0


def _print_health(report: dict) -> int:
    """Render the readiness checklist the way the phone UI does.

    Exit code is 0 only when nothing blocking is wrong, so this is usable as a
    setup gate in a script: ``castcast doctor && castcast serve``.
    """
    print(f"castcast {report.get('version')} on Python {report.get('python')}")
    print()
    for check in report.get("checks") or []:
        if check["ok"] is True:
            mark = "ok  "
        elif check["ok"] is False:
            mark = "FAIL" if check["blocking"] else "warn"
        else:
            mark = "?   "
        print(f"{mark} {check['label']}")
        if check.get("detail"):
            print(f"       {check['detail']}")
        if check["ok"] is not True and check.get("remedy"):
            print(f"       -> {check['remedy']}")
    print()
    if report.get("ready"):
        print("ready. start the daemon with:")
        print(f"  $ {report.get('serve_command')}")
        return 0
    print("not ready -- fix the FAIL rows above.", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="castcast",
                                     description="Google-Home-free Chromecast controller")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--media-root", action="append", dest="media_roots")
    parser.add_argument("--host", help="Chromecast IP (skips discovery)")
    parser.add_argument("--port", type=int, default=8009)

    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the daemon")
    serve.add_argument("--api-port", type=int)
    serve.add_argument("--api-host")
    serve.add_argument("--quiet", action="store_true")

    sub.add_parser("devices", help="discover Chromecasts on the LAN")

    check = sub.add_parser("check", help="pre-flight a file without casting")
    check.add_argument("path")
    check.add_argument("--json", action="store_true")

    prep = sub.add_parser("prepare", help="remux/convert a file for casting")
    prep.add_argument("path")
    prep.add_argument("--force", action="store_true")

    cast = sub.add_parser("cast", help="cast a file")
    cast.add_argument("path")
    cast.add_argument("--allow-unsafe", action="store_true",
                      help="send the LOAD even if we predict it will fail")

    sub.add_parser("scan", help="pre-flight every file in the media roots")

    doctor = sub.add_parser("doctor", help="check tools, storage and LAN readiness")
    doctor.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.media_roots:
        config["media_roots"] = args.media_roots
    if args.host:
        config["static_host"] = args.host
        config["static_port"] = args.port

    service = CastService(config)

    # ---- non-daemon commands -------------------------------------------
    if args.command == "devices":
        service.media_server.start()
        devices = service.discover()
        if not devices:
            print("no Chromecasts found.\n"
                  "  - mDNS multicast is often dropped by routers and by Android's\n"
                  "    Wi-Fi stack; this is the least reliable part of the stack.\n"
                  "  - If you know the device's IP, skip discovery entirely:\n"
                  "      castcast --host 192.168.1.50 cast <file>\n"
                  "    or set \"static_host\" in the config. Pinning the IP in your\n"
                  "    router's DHCP reservations is the most reliable setup.",
                  file=sys.stderr)
            return 1
        for device in devices:
            flag = "  <- Ultra" if device.get("is_ultra") else ""
            print(f"{device['host']:<16} {device['friendly_name']:<28} "
                  f"{device['model']:<20} [{device['source']}]{flag}")
        return 0

    if args.command == "check":
        report = service.preflight(os.path.abspath(args.path))
        if args.json:
            print(json.dumps(report, indent=2, default=str))
            return 0
        return _print_report(report)

    if args.command == "scan":
        rows = service.library(deep=True)
        if not rows:
            print("no media found in: " + ", ".join(service.media_roots))
            return 1
        for row in rows:
            verdict = row.get("verdict") or {}
            video = ((row.get("media") or {}).get("video") or [None])[0]
            res = f"{video['width']}x{video['height']}" if video else "?"
            if row.get("tools_missing"):
                mark = "??  "
            elif row.get("error"):
                mark = "ERR "
            elif not verdict.get("needs_processing"):
                mark = "OK  "
            elif verdict.get("video_action") == "transcode":
                mark = "SLOW"
            else:
                mark = "FIX "
            print(f"{mark} {res:<11} {row['rel']}")
            if verdict.get("issues"):
                for issue in verdict["issues"]:
                    if issue["severity"] == "fatal":
                        print(f"       - {issue['message']}")
        return 0

    if args.command == "doctor":
        service.media_server.start()
        try:
            report = service.health()
        finally:
            service.media_server.stop()
        if args.json:
            print(json.dumps(report, indent=2, default=str))
            return 0 if report["ready"] else 1
        return _print_health(report)

    if args.command == "prepare":
        service.media_server.start()
        result = service.prepare(os.path.abspath(args.path), force=args.force)
        if result.get("error"):
            print(f"error: {result['error']}", file=sys.stderr)
            return 1
        if not result.get("started"):
            print("nothing to do -- the file is already castable.")
            return 0
        while service._remuxer.busy:  # noqa: SLF001
            job = service._remuxer.job  # noqa: SLF001
            if job:
                sys.stdout.write(f"\r  converting... {job.progress * 100:5.1f}%")
                sys.stdout.flush()
            time.sleep(0.5)
        print()
        job = service._remuxer.job  # noqa: SLF001
        if job and job.state == "done":
            print(f"done: {job.plan.output_path}")
            return 0
        print(f"failed: {job.error if job else 'unknown'}", file=sys.stderr)
        return 1

    if args.command == "cast":
        if not config.get("static_host"):
            print("error: --host is required for one-shot casting "
                  "(or set static_host in the config)", file=sys.stderr)
            return 1
        service.start()
        if service.supervisor and not service.supervisor.wait_for(
                ["connected", "ready", "playing"], timeout=20.0):
            print("error: could not establish a connection", file=sys.stderr)
            return 1
        result = service.cast(os.path.abspath(args.path),
                              allow_unsafe=args.allow_unsafe)
        if result.get("error"):
            print(f"error: {result['error']}", file=sys.stderr)
            _print_report(result)
            return 1
        print(f"casting: {result.get('url')}")
        try:
            _tail_logs(service)
        except KeyboardInterrupt:
            service.stop()
        return 0

    # ---- serve ----------------------------------------------------------
    if args.api_host:
        config["api_host"] = args.api_host
    if args.api_port:
        config["api_port"] = args.api_port

    service.start()
    api = ApiServer(service, config["api_host"], int(config["api_port"]))
    api.start()

    service.log(f"control API on http://{config['api_host']}:{api.port}")
    service.log(f"media server on {service.media_server.base_url}")

    stopping = {"flag": False}

    def shutdown(_signum, _frame):
        if stopping["flag"]:
            return
        stopping["flag"] = True
        service.log("shutting down")
        api.stop()
        service.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if args.quiet:
        while not stopping["flag"]:
            time.sleep(0.5)
    else:
        try:
            _tail_logs(service)
        except KeyboardInterrupt:
            shutdown(None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
