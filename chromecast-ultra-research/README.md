# Chromecast Ultra research and diagnostic notebook

Started 2026-09-06. This is a partial evidence notebook, not a completed hardware qualification or authorization to patch the application. No Ultra playback tests have been performed for it yet.

## Product contract clarified by the owner

- Target this owner's phone and Ultra. Establish functionality before security hardening; no security changes during this investigation.
- Preserve working features. Removing a blocking check is not sufficient evidence that a feature works.
- Play legitimate SD/HD/1080p content normally. Allow adaptive startup and resolution/bitrate changes without automatic below-4K pauses or rejection.
- Preserve source quality during local processing. Source properties, available representations, current decoded video and HDMI output are different observations.
- Prioritize verbose, actionable diagnostics: operation, session, timing, exception and original failure. Distinguish provider, network, decoder and application failures.
- Investigate one demonstrated failure at a time against the working baseline. Hardware behavior takes precedence over assumptions; untested hypotheses must not become admission gates.

## Reading map

- [Transport and endpoints](transport-and-endpoints.md)
- [Media and receivers](media-and-receivers.md)
- [Providers and observability](providers-and-observability.md)
- [Hands-on baseline and tour](hands-on-baseline.md)

The research chapters record source links, evidence qualifications and pending questions. Community implementation proves what that project does, not universal Ultra support. Device reports must retain device/player/firmware versions where available. Official codec declarations are not end-to-end playback guarantees. Historical workarounds need freshness checks. Emulator/mock success is not stock-device evidence.

## Status and source preservation

The first pass was redirected toward a credit-conscious phone diagnostic tour when ADB became available. It is not an exhaustive claim to know the Ultra inside out. Public source downloads encountered network failures; no offline clone archive was verified. Follow the cited sources and pin revisions when reproducing findings.

The repository changed during the owner's rollback. Initial inspection: `f5cc6548786873f41476b32b5d5ff625a6548d05`. Phone-baseline inspection: `f406dc1d58839649e87f1c416cb2ad66bb5f2cde`. Neither is proven to identify the deployed APK/Python code. Older PR #65 findings must be rechecked before describing them as current bugs.

This directory was used because the existing `docs/` directory was not writable in the current filesystem mapping. No existing permissions were changed. No application source, installed package, receiver configuration or playback state was changed to create this notebook.
