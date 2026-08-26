<!-- WARNING: Editing this file or ignoring its contents during feature development may cause catastrophic app desynchronization between the Android App, Termux daemon, and Chromecast components. -->

# CastCast Synchronization Map & Checklist

This document is the authoritative inventory of architectural components, their roles, and their boundaries. It replaces the old scenario-based narrative with stable section IDs, inventories, and contract definitions.

## Feature Placement Algorithm

When adding a new feature or file, determine its placement using the following algorithm:

1. **Does it provide HTTP endpoints or SSE events?** -> `api-contract`
2. **Is it a core daemon service/orchestrator?** -> `core-service`
3. **Does it handle media streaming or proxying?** -> `media-routing`
4. **Is it a standalone utility/middleware (e.g., metadata extraction)?** -> `utility-middleware`
5. **Is it a web client adapter or UI component?** -> `web-client`
6. **Does it bridge Android native code and web?** -> `android-bridge`
7. **Is it related to the Chromecast receiver/sender?** -> `cast-sender-receiver`
8. **Does it handle configuration or persistent state?** -> `config-state`
9. **Is it a build script, daemon bootstrap, or release artifact?** -> `operations-release`

## Stable Section IDs & Inventories

*   **`core-service`**: Core daemon logic and orchestration. (e.g., `daemon/castcast/service.py`)
*   **`api-contract`**: HTTP routes, SSE events, and frontend wrappers. (e.g., `daemon/castcast/api.py`, `src/app/lib/daemon.ts`)
*   **`media-routing`**: Proxying, DRM, and media delivery. (e.g., `daemon/castcast/mediaserver.py`)
*   **`utility-middleware`**: Standalone utilities and metadata extraction. (e.g., `daemon/castcast/metadata.py`)
*   **`web-client`**: Frontend application and React components. (e.g., `src/app/App.tsx`)
*   **`android-bridge`**: Capacitor plugins and Android native code. (e.g., `TermuxDaemonPlugin.java`)
*   **`cast-sender-receiver`**: Chromecast receiver HTML/JS and sender logic. (e.g., `daemon/castcast/receiver/index.html`)
*   **`config-state`**: Configuration files and persistent state storage.
*   **`operations-release`**: Build scripts, daemon bootstrap, and release artifacts. (e.g., `termux_bootstrap.sh`)

## Contract Tables

### HTTP Routes
| Method | Path | Request Schema | Response Schema | Error Codes | Daemon Owner | Frontend Wrapper | Test |
|---|---|---|---|---|---|---|---|
| POST | `/new_queue/add` | ... | ... | ... | `api.py` | `daemon.ts` | ... |
| GET | `/diagnostics/logs` | ... | ... | ... | `api.py` | `App.tsx` | ... |

### SSE Events
| Name | Producer | Payload Schema | Frontend Subscriber/State Owner | Ordering/Replay Behavior | Test |
|---|---|---|---|---|---|
| `new_queue` | `service.py` | `{"items": [...]}` | `daemon.ts` | ... | ... |
| `status` | `supervisor.py` | `{...}` | `App.tsx` | Single source of truth | ... |

### Config/Env Keys
| Default | Owner | Type | Secret Classification | Validation | Health/UI Display | Migration |
|---|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... | ... |

### Persistent State
| Path | Schema/Version | Writer | Readers | Migration/Rollback | Test |
|---|---|---|---|---|---|
| `~/.config/castcast/new_queue.json` | JSON | `service.py` | `service.py` | ... | ... |

### Native Plugins
| TypeScript Signature | Java Method/Event | Registration | Permissions | Lifecycle Behavior | Test |
|---|---|---|---|---|---|
| `TermuxDaemonPlugin` | `launchTermux` | Capacitor | ... | ... | ... |

### Receiver Contract
| Sender Producer | Receiver Consumer | Payload Shape/Defaults | Compatibility Policy | Test |
|---|---|---|---|---|
| `supervisor.py` | `index.html` | ... | ... | ... |

### Build Artifacts
| Source | Output | Generation Command | Whether Committed | Freshness Check |
|---|---|---|---|---|
| `daemon/` | `dist/daemon/` | `npm run build` | No | CI check |
