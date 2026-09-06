# CastCast: Chromecast Ultra research questions

Prepared 6 September 2026 for Don and the CastCast engineering team. Initial research brief and CLI handoff; Gemini revision review pending.

**Working baseline**

Don reports reliable Amazon 4K playback with subtitles and a recently fixed subtitle delay after seeking. Treat those capabilities as the baseline to preserve. This brief does not reopen whether they are possible. The immediate objective is useful, detailed diagnostics; the longer-term objective is reusable support for other authorized DRM-protected services, with the receiver's DRM enforcement intact.

At the initial check, published main was a754cb5bd9cd8817392f32aba43288a8fe40e61a and PR #65 remained at b31b9774ffc800a976fca16512faf1be68f479d5. Gemini is still working. Neither snapshot should be assumed to represent the latest installed, working phone build. No repository, phone, receiver, or provider-session changes were made for this brief.

**What “unanswered” means here**

A search cannot establish that nobody has ever answered a question. The labels below distinguish:

| Label | Meaning |
| --- | --- |
| Research gap | No sufficiently specific published answer was found in the sources reviewed for this combination of Ultra, deployed receiver, and workflow. A candidate for original investigation. |
| Device verification | The mechanism is published; its availability or behavior on the actual installed combination remains unverified. |
| Integration question | The answer depends on CastCast or a future provider adapter. It is engineering work, not automatically a new Chromecast discovery. |

P0 means needed for trustworthy diagnostics. P1 supports recovery and service expansion. P2 is a later capability experiment. A missing field, rejected request, or failed experiment is an observation with a scope, not proof of impossibility.

**Published foundations to use, not rediscover**

- Shaka's Cast implementation forwards playback events and attributes, and periodically sends player getters. Large results travel in separate update messages. The examined source includes buffer information, expiry, key-status metadata, statistics, configuration, and track lists. This establishes candidate telemetry, not the exact deployed receiver contract. [Cast bridge](https://github.com/shaka-project/shaka-player/blob/main/lib/cast/cast_receiver.js), [wire definitions](https://github.com/shaka-project/shaka-player/blob/main/lib/cast/cast_utils.js).
- Shaka supports asynchronous external-track loading. A historical sender-to-receiver transfer bug and its receiver-side workaround are documented. External subtitles are not inherently incompatible with casting. [Maintainer explanation](https://github.com/shaka-project/shaka-player/issues/3370#issuecomment-937059179).
- Cast application connections and media sessions differ from the underlying TLS socket. VLC distinguishes application closure and takeover; PyChromecast implements device discovery and setup-request compatibility handling. [VLC](https://github.com/videolan/vlc/blob/master/modules/stream_out/chromecast/chromecast_ctrl.cpp), [PyChromecast](https://github.com/home-assistant-libs/pychromecast/blob/master/pychromecast/dial.py).
- The demo receiver is a specific application with its own asset/configuration contract. Capture its observed app ID, namespaces, and player build separately from firmware; an app ID alone does not identify the JavaScript currently executing. [Demo receiver](https://github.com/shaka-project/shaka-player/blob/main/demo/cast_receiver/receiver_app.js), [asset parser](https://github.com/shaka-project/shaka-player/blob/main/demo/common/asset.js).

**Questions and experiments**

**Q01 — Which exact receiver and player implementation is executing the successful Amazon session?**

P0 · Device verification.

Published boundary: the demo loads web/player resources; source on main is not proof of the active device build. Record firmware, receiver app ID, advertised namespaces, transport/session identifiers, and any legitimately exposed player/build identity. Record APK version/hash and loaded daemon source identity on the phone. Repeat identity collection across ordinary later sessions without forcing an update or clearing caches. If no player-version field is exposed, document that limit and retain a behavioral fingerprint rather than inventing a version.

Useful result: an evidence-based compatibility profile that can detect changes independently in firmware, receiver, APK, and daemon. Sources: demo receiver and asset parser above.

**Q02 — Which useful telemetry can the existing Shaka receiver deliver without replacing or reloading it?**

P0 · Device verification.

Published boundary: candidate getters are enumerated in CastUtils. Observe normal Cast traffic through the existing sender, then compare the observed fields with those definitions. Inventory presence, type, update cadence, and session scope for buffer ranges, dimensions, bandwidth estimates, decoder counters, track lists, expiry, and key-status metadata. An absent field must be classified as absent, unobserved, undecoded, or inaccessible—not converted to zero.

Useful result: a supported diagnostic field catalogue for this receiver. Source: [CastUtils](https://github.com/shaka-project/shaka-player/blob/main/lib/cast/cast_utils.js).

**Q03 — After a seek, item change, or reconnect, which reported values are fresh, stale, or from a previous session?**

P0 · Research gap.

Published boundary: updates can arrive separately and at different frequencies. Capture complete ordered message envelopes during ordinary play, seek, pause, and resume. Track each field's last observation and associate it with transport, application session, media session where meaningful, asset, and local load generation. Look for old dimensions, track IDs, buffer ranges, or statistics arriving after a transition. Do not assume requestId alone provides an ordering across all namespaces or senders.

Useful result: rules for merging telemetry without manufacturing a coherent-looking but stale snapshot. Source: [receiver update scheduling](https://github.com/shaka-project/shaka-player/blob/main/lib/cast/cast_receiver.js).

**Q04 — What is the smallest trace that distinguishes transport, proxy/CDN, license, buffer, and decoder failures?**

P0 · Research gap.

Published boundary: Shaka exposes several relevant statistics, but a universal classifier for this phone/proxy/Ultra setup was not found. Start with successful playback as the control. Align command send/receive times, heartbeat observations, proxy request phases, buffer ranges, player errors, key statuses, and decoded/dropped-frame counters where available. Later use isolated faults in owned test fixtures to see which diagnoses are distinguishable. A buffered player with no clock progress is not, by itself, proof of a decoder fault.

Useful result: a diagnostic explanation with supporting evidence and confidence instead of a generic “disconnected” message. [Statistics implementation](https://github.com/shaka-project/shaka-player/blob/main/lib/util/stats.js).

**Q05 — How accurately can the APK, daemon, network activity, and receiver events share one timeline?**

P0 · Research gap.

There is no established clock-error budget for this arrangement. Record wall time, monotonic receipt/send times, clock domain, and process/boot identity. Measure round-trip bounds where a request has a matching response. Separate the media presentation clock from host elapsed time; receipt time is not receiver event-generation time. Evaluate ordinary seeks and screen-off periods, including phone suspend behavior. State the uncertainty when two events cannot be ordered confidently.

Useful result: timing claims such as “subtitle selection was acknowledged before the seek completed” that can actually be defended. This is a measurement-design question, not a missing Cast command.

**Q06 — Can logging and observation themselves induce the stalls being investigated?**

P0 · Research gap.

Published boundary: Google documents resource exhaustion from prolonged receiver debugger attachment. Compare the same workflow with normal logging, bounded structured logging, and any legitimately available richer capture. Measure phone CPU/memory/thermal state, event backlog, disk-write latency, playback counters, and symptom frequency. Do not assume a debugger is available for the public demo receiver or leave one attached as the default logging mechanism.

Useful result: measured logging budgets and sampling rules, including explicit dropped-event counts. [Debugger constraints](https://developers.google.com/cast/docs/debugging/remote_debugger), [phone diagnostics](https://developer.android.com/tools/dumpsys).

**Q07 — What diagnostic evidence survives each kind of process or connection loss?**

P0 · Integration question.

Published main assembles recent daemon entries and a bounded tail of an audit file, which does not establish durability for Gemini's revision. After reviewing that revision, insert harmless correlation markers through normal log paths. In a controlled test session, check persistence across controller closure, daemon restart, and SSE resubscription separately. Record the last persisted event, missing sequence intervals, rotation behavior, and whether the first session after restart is incorrectly joined to the previous one.

Useful result: a restart-surviving incident bundle with explicit gaps. [Published diagnostics implementation](https://github.com/1456319/CastCast/blob/a754cb5bd9cd8817392f32aba43288a8fe40e61a/daemon/castcast/api.py).

**Q08 — Which timing invariant does the subtitle-seek fix restore, and does it hold across other stream timelines?**

P0 · Integration question, followed by a research gap.

First read Gemini's actual fix; do not guess its mechanism. Then test forward/backward seeks, rapid consecutive seeks, language changes, and period/discontinuity boundaries using media with known timing. Record requested and settled media time, subtitle format, cue timestamps, manifest period/segment offsets, and observed rendering where available. Text-track selection is not proof that a cue appeared on time. Shaka explicitly handles different VTT timing contexts and HLS timestamp mapping; those known rules supply the test cases.

Useful result: a reusable timing diagnostic and regression fixture, rather than another fixed subtitle delay. [VTT parser](https://github.com/shaka-project/shaka-player/blob/main/lib/text/vtt_text_parser.js), [TTML parser](https://github.com/shaka-project/shaka-player/blob/main/lib/text/ttml_text_parser.js).

**Q09 — Which subtitle identities and selections survive reload, reattachment, and provider transitions?**

P1 · Research gap.

Published boundary: synthetic external tracks have historically required explicit transfer to the receiver. Observe manifest and external-track identities through ordinary transitions, including “off,” forced captions, and same-language alternatives. Correlate application track identity, receiver-assigned ID, source metadata, asynchronous completion, and visible selection. Determine when IDs are reused or remapped and whether missing receiver tracks mean deletion or an incomplete update.

Useful result: captions remain selected and correctly labelled without losing their source metadata. [Historical transfer issue](https://github.com/shaka-project/shaka-player/issues/3370), [current asynchronous bridge](https://github.com/shaka-project/shaka-player/blob/main/lib/cast/cast_receiver.js).

**Q10 — Which read-only setup endpoints expose useful network/device diagnostics on this Ultra firmware, and in which states?**

P1 · Device verification.

Published boundary: GHLocalApi describes Eureka fields and historical authentication; PyChromecast uses HTTPS 8443, HTTP 8008 fallback for some reads, and a targeted Host-header retry after 403. On the identified Ultra only, inventory known read-only requests such as /setup/eureka_info and documented field selectors. Record scheme, port, path, parameter spelling, Host form, authorization mode, HTTP status, latency, and returned field names in idle and playback states. “params” is the implemented query name in the examined schema despite prose saying “param.” Do not call configuration, scan, reboot, or reset endpoints as diagnostics.

Useful result: a firmware-scoped endpoint capability map. [Historical schema](https://github.com/rithvikvibhu/GHLocalApi/blob/master/GoogleHome.openapi3.json), [working client implementation](https://github.com/home-assistant-libs/pychromecast/blob/master/pychromecast/dial.py).

**Q11 — Can the controller reattach after losing its connection while preserving the receiver's current DRM session and subtitles?**

P1 · Research gap.

Published boundary: virtual connections can be established independently of launching an application. In a dedicated test session, reconnect the sender and request existing state before issuing LOAD. Observe whether playback, subtitle selection, app transport, media identity, and license activity persist. Compare controller-process loss, TCP loss, receiver-app closure, and genuine takeover as different cases. A missing sender connection does not establish that the receiver stopped.

Useful result: recovery that preserves ongoing playback whenever possible. [Cast V2 reverse-engineered protocol](https://github.com/thibauts/node-castv2), [VLC state handling](https://github.com/videolan/vlc/blob/master/modules/stream_out/chromecast/chromecast_ctrl.cpp).

**Q12 — Which requests in successful playback actually traverse the phone, and which go directly from the Ultra to a remote server?**

P0 · Integration question.

Establish the route of manifests, video/audio segments, subtitle resources, licenses, certificates, and tunnel traffic. Correlate daemon HTTP logs with phone sockets and, where available, receiver/player telemetry. Phone packet capture sees traffic through the phone and the phone's interfaces; it does not automatically observe all Ultra-to-CDN traffic on a switched network. TLS packet timing does not expose application payloads. State which hops remain unobserved.

Useful result: instrumentation at the correct hop and accurate attribution of connection failures. The actual route is an application fact to measure, not something established by Chromecast port lists.

**Q13 — Which expiry or refresh events can disrupt playback, and can each recover without a new LOAD?**

P1 · Research gap.

Distinguish account authorization, signed manifest/segment URLs, license-server authorization, the CDM license itself, and tunnel availability. Observe normal expiry/refresh cycles and test short lifetimes only with controlled fixtures. Keep the stable receiver-facing proxy route constant while refreshing authorized upstream credentials where the application supports it. Record whether a change causes a license request, content reload, buffer loss, or subtitle reset. Published token-refresh advice establishes a mechanism, not the complete behavior of this provider path.

Useful result: renewal and tunnel recovery that do not unnecessarily restart media. [Maintainer discussion](https://github.com/shaka-project/shaka-player/issues/1348#issuecomment-371650322).

**Q14 — What accessible evidence distinguishes selected UHD, decoded UHD, HDR metadata, and the TV's actual output mode?**

P1 · Research gap.

The current 4K success is the baseline; this question concerns diagnostic proof and detection of future regressions. Compare representation/codec metadata, available player dimensions/counters, reported HDR information, and the TV/AVR information display. Identify disagreement and missing evidence rather than treating every field as equivalent. Include cropped UHD content and adaptive startup. Receiver video dimensions alone do not establish HDMI mode; if that mode is not remotely observable, retain a labelled external observation.

Useful result: truthful quality diagnostics without the draft's automatic PAUSE behavior. [Cast video information](https://developers.google.com/cast/docs/reference/web_receiver/cast.framework.messages.VideoInformation), [Shaka statistics](https://github.com/shaka-project/shaka-player/blob/main/lib/util/stats.js).

**Q15 — What buffer and resource envelope preserves sustained UHD and responsive seeking on this combination?**

P2 · Research gap.

A historical Ultra report linked tiny buffer-removal intervals to receiver crashes; it is closed and is not evidence of a current defect. Establish normal playback first. Then vary one supported buffer parameter at a time with controlled media while holding quality and subtitle workload constant. Compare seek latency, buffer ranges, frame counters, and memory/thermal observations that are actually available. Phone memory is not receiver memory. Use onset of instability as a stopping condition, not a target for stress or fuzzing.

Useful result: measured buffer settings and early-warning signals for this firmware/player combination. [Historical Ultra report](https://github.com/shaka-project/shaka-player/issues/6240).

**Q16 — Which complete media combinations work through this receiver, beyond the already working Amazon combination?**

P2 · Device verification.

Build a matrix of codec/profile/level, container, encryption scheme, frame rate, HDR, audio layout, subtitle format, and transitions between them using authorized test assets. Test capability reporting and actual playback separately. An Ultra codec-string workaround was investigated and rejected after real decoding failed; a closed codec-switching report also illustrates why old issue titles are insufficient. Record version and outcome rather than extrapolating from Google TV or another Cast model.

Useful result: provider preflight based on tested combinations without manipulating DRM enforcement. [Ultra codec investigation](https://github.com/shaka-project/shaka-player/issues/7888#issuecomment-2683277796), [historical codec-switching report](https://github.com/shaka-project/shaka-player/issues/5306).

**Q17 — Which parts of the working Amazon integration are genuinely reusable as an authorized provider adapter?**

P1 · Integration question.

After reviewing the working revision, inventory authentication/refresh, playback metadata, manifest addressing, license request/response envelopes, certificate delivery, and subtitle discovery. For the next selected service, map each difference to phone-side transport/configuration or receiver-side behavior. The demo asset parser exposes configuration and license-server/header fields, but arbitrary JavaScript request filters cannot simply be serialized into JSON. Keep DRM challenge/license processing within the authorized exchange and receiver CDM; a service requiring another receiver contract is a measured boundary, not a reason to weaken DRM.

Useful result: a small provider interface with explicit supported and unresolved requirements. [Asset parser](https://github.com/shaka-project/shaka-player/blob/main/demo/common/asset.js), [historical filter limitation](https://github.com/shaka-project/shaka-player/issues/1348#issuecomment-371562007).

**Q18 — Can diagnostics distinguish license transport success from actual usable keys and enforced output policy?**

P1 · Research gap.

Published boundary: EME exposes key-status and expiry concepts; Shaka's bridge lists corresponding getters. Observe initial acquisition, renewal, and key rotation where present in authorized content. Correlate request status/timing with available normalized key-status changes and playback progress. A successful HTTP response is not proof that the CDM accepted usable keys. Capture status categories and investigation-local identifiers rather than raw license bodies or credentials. Do not assume that every standard EME method is exposed by this older receiver.

Useful result: errors that identify the failing layer while preserving DRM decisions. [EME Recommendation](https://www.w3.org/TR/2017/REC-encrypted-media-20170918/), [Shaka getter definitions](https://github.com/shaka-project/shaka-player/blob/main/lib/cast/cast_utils.js).

**Q19 — What is the first observable divergence between intent, files, queues, receiver state, and UI?**

P0 · Integration question.

Follow one queue operation through the revision's real contracts: user intent, daemon acceptance, persistence, filesystem change where applicable, receiver acknowledgment, later observation, and UI update. Use stable application asset/operation identities alongside receiver-scoped IDs. Include partial status updates, provider episodes without local files, and reconnect. Do not assume Shaka has the Default Media Receiver's native queue interface. A returned acknowledgment is not automatically a complete queue snapshot.

Useful result: logs identify the first broken transition and can reconstruct what each layer believed at that time. Review dependency: [CastCast synchronization map](https://github.com/1456319/CastCast/blob/main/docs/SYNCHRONIZATION_MAP.md) and Gemini's replacement contracts.

**Q20 — Which receiver-side recovery and control operations work in each player state without losing quality, subtitles, or the licensed session?**

P2 · Research gap.

Published source lists operations such as retryStreaming, track selection, and configuration changes. Build a state-specific command/response matrix from those supported operations after passive capture is reliable. Test the least disruptive recovery first in controlled fixtures and record both acceptance and observed effect. Compare retrying media fetches, refreshing configuration, reattaching control, and reloading content. A method's presence in JavaScript does not prove that it is useful or safe in every player state.

Useful result: a recovery policy and additional user controls backed by measured preconditions. [Shaka proxied operations](https://github.com/shaka-project/shaka-player/blob/main/lib/cast/cast_utils.js).

**CLI handoff: observation before experimentation**

1. Review Gemini's completed revision and identify the installed working APK/daemon before attributing behavior to source. Preserve the subtitle fix and working Amazon path. PR #65 is not the baseline.
2. Identify the phone and the user's Ultra specifically. ADB provides access to the phone; it does not grant root, logcat, or arbitrary internal access on the Ultra. Use existing application logs and owned sender/proxy instrumentation for decrypted protocol data. Treat receiver debugging as available only when legitimately exposed for that application/device; the documented debugging workflow requires the app and device to share a developer account.
3. Capture one normal playback session with subtitles, ordinary seeks, pause/resume, and screen-off behavior. Record the exact human actions. Do not replace the receiver, modify global TLS settings, alter Android permissions, restart the daemon, or change network configuration during this baseline capture.
4. Answer Q01, Q02, Q03, Q05, and Q12 first. Resolve the revision-specific portions of Q07, Q08, and Q19 before proposing instrumentation changes.
5. Map gaps to a minimal logging patch only after source review. Keep observation and control paths separate so logging cannot trigger LOAD, track changes, or reconnection.
6. Run controlled experiments one variable at a time, starting with owned/unprotected timing fixtures and then confirming applicable behavior in authorized provider playback. Keep a return-to-baseline procedure. Do not use factory reset, firmware changes, endpoint fuzzing, permission bypasses, or DRM modification as exploration techniques.
7. Return evidence, limitations, and a concrete integration candidate for each answered question. Leave unanswered questions open when the necessary observation point is unavailable.

This brief is an investigation plan, not authorization to launch experiments now. No ADB session or hardware experiment has been performed in this conversation.

**Minimum useful diagnostic record — proposed design**

| Group | Fields to retain when available |
| --- | --- |
| Provenance | Schema version, investigation ID, APK/daemon identity, firmware, receiver/player identity, configuration revision, process/boot identity. |
| Timing | UTC timestamp, local monotonic timestamp, clock domain, send/receive timestamps, measured uncertainty; media presentation time separately. |
| Correlation | Operation ID, connection generation, Cast source/destination/namespace, request ID, app/media session scope, application asset ID, manifest generation, track/representation IDs. |
| Network | Request role, route/hop, attempt, status, MIME type, byte count/range, first-byte/completion latency, redirect relationship, cancellation/timeout. |
| Playback | Player state, current time, separate audio/video/text ranges when exposed, selected tracks, reported dimensions, frame/bandwidth counters, structured error category/code. |
| DRM metadata | Normalized status categories, expiry where exposed, exchange timing/result, request role; opaque investigation-local identifiers. |
| Integrity | Per-producer sequence, persisted watermark, dropped-event count, truncation, stale/missing/redacted flags, logger backlog. |

Preserve the envelope and sanitized payload structure at the owned sender boundary, then derive the readable event. Shaka's serialization includes special handling for TimeRanges, events/errors, byte arrays, and non-finite numbers. Preserve the difference between absent, null, zero, NaN, Infinity, and redacted values. Do not log an undecoded event as if it contained no error. [Serialization implementation](https://github.com/shaka-project/shaka-player/blob/main/lib/cast/cast_utils.js).

Use investigation-local opaque tags or keyed digests to correlate sensitive URLs and identifiers; do not export their key. Retain useful timing and request relationships while excluding authorization headers, cookies, credential values, raw DRM challenges/licenses, and decrypted media from routine diagnostic exports. Reproducible synthetic fixtures can carry non-sensitive payload examples. These logging choices must not change requests sent to the receiver or provider.

**What counts as an answer or a discovery**

For every finding return: question ID; classification; exact hardware/firmware/app builds; preconditions; actions; sanitized observed request/response sequence; outcome; repetition count; competing explanations; unavailable observations; nearest published evidence; proposed integration and a regression case. Label findings as observed, reproduced, inferred, not observed, or inaccessible.

An isolated successful request is a lead. A repeatable behavior with its preconditions, failure boundary, and a usable integration is a stronger finding. Call it novel only relative to the documented search scope; discovery on one Ultra is not proof for every firmware or Cast model.

**Research coverage and limits**

Reviewed primary source code from Shaka's Cast bridge, demo asset parser, statistics and text parsers; maintained Cast-client implementations in PyChromecast and VLC; the original node-castv2 reverse-engineering notes; GHLocalApi's historical schema and authentication/403 work; targeted Shaka maintainer discussions on text transfer, token refresh, Ultra buffer eviction, codec limits and switching; Cast debugger and video-information references; Android dumpsys; and EME status semantics. Shaka main/master references and public demo source were inspected on 6 September 2026; they are moving references and must be pinned when creating reproducible test cases.

Targeted issue searches covered Chromecast subtitle seeking, Ultra buffering, license renewal, and HDCP. General web searches also supplied discovery leads; irrelevant results and reports about different hardware were not treated as Ultra evidence. Several historical issues are closed. No complete Internet census, exhaustive issue-history review, public novelty proof, receiver firmware analysis, or new-service compatibility test has been performed. No next provider has been selected, so provider-specific entitlement and license requirements remain outside this initial brief.

The strongest candidates for new device knowledge are Q03–Q06, Q08's cross-timeline behavior, Q09, Q11, Q13–Q15, Q18, and Q20. Q01, Q02, Q10, and Q16 prevent rediscovering published capabilities. Q07, Q12, Q17, and Q19 turn evidence into useful CastCast engineering.
