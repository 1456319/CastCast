# Chromecast Ultra (`steak` / `luther-b4` / `bg4cdp_tyson`): Ground-Truth Monograph & Empirical Telemetry Dossier

**Target Hardware:** Google Chromecast Ultra (`NC2-6A5-D`, FCC ID `A4RNC2-6A5-D`), EOL final stable firmware **`1.56.469779`** (`build_version: 469779`)  
**Purpose:** Durable, high-precision technical synthesis prepared for automated analysis (including Google Neon) covering primary discoveries from GPL/OSS drops, Silicon/USB Mask-ROM probing, bootloader cryptography bounds, Omaha Update2 oracle testing, and Cast runtime behavior—data that is absent from, or directly contradicted by, standard public web summaries.

> **Epistemic & Sanitization Contract**
> 1. Every register, hash, offset, USB descriptor, log timestamp, and negative bound below was directly observed in primary device captures, local reverse-engineering artifacts, or upstream source trees (`chromecast_sdk_oss/steak`, `chromium/src/chromecast`, `caramelkat/PodiumFlashing`, `coggy9/HKHacking`, `Cronick/WV-System-ID-Overview`).
> 2. Where an inference or hypothesis remains open, it is explicitly labeled **[UNCONFIRMED]** or **[OPEN HYPOTHESIS]**.
> 3. Local LAN/RF identifiers (Wi-Fi SSID, BSSID, hotspot BSSID, device MAC, SSDP UDN UUID, LAN IPs, router vendor/API host, and the device's per-unit RSA-2048 public key) have been sanitized to placeholders (`<REDACTED_*>`).

---

## 1. Starting at `lexx` and `luther`: Why Public Models Hallucinate This Architecture

### 1.1 Anatomy of a Confabulation

When prompted for the meaning of `Lexx` / `Luther` alongside **Chromecast Ultra**, generic search summaries and LLM overviews (including Google Neon) repeatedly fail along predictable associative seams:
- **Confabulation A — Stadia Comics Crossover:** Neon claimed that *"Chromecast Ultra ambient-mode advertisements frequently featured Lex Luthor in his green-and-purple warsuit as part of the marketing push for Injustice 2 and DC Universe Online arriving on Stadia."*  
  - **Disproof:** Neither *Injustice 2* nor *DC Universe Online* was ever released on Google Stadia (the only NetherRealm fighting title released on Stadia was *Mortal Kombat 11*).
- **Confabulation B — Hardware & Assistant Conflation:** Neon tied `Luthor` to *"Marlin / Sailfish era, specifically B4 / NC2-6A5 hardware IDs"* and invented a Google Assistant Voice Match bug misparsing *"Lex Luthor"* as a Cast target.  
  - **Disproof:** `Marlin`/`Sailfish` are 2016 Pixel phones (`Pixel XL` / `Pixel`). **`NC2-6A5`** (`A4RNC2-6A5`) is the **2nd-generation 1080p Chromecast** (2015); the Chromecast Ultra's regulatory model is **`NC2-6A5-D`** (`A4RNC2-6A5-D`). Meanwhile, **`luther-b4`** and **`lexx-b4`** are internal Google hardware board-revision identifiers baked directly into shipped bootloaders and Widevine keybox tables.
- **Confabulation C — Categorical Denial by Search AI:** Live web-search summarizers asserted *"Lexx / Earth: Not standard Google hardware codenames"* and *"Caprica: Not typically associated with a Google Home or display"*—while Google's own GPL drops define both `BOARD_LEXX_*` and `BOARD_EARTH_*` in C headers, and Widevine L1 System ID registries list `Caprica/caprica-b4` right next to `Estelle/estelle-b4`.

**Why this blind spot exists:** Consumer tech press leaked music/sitcom codenames (`hendrix`, `joplin`, `biggie`, `estelle`, `newman`), whereas the early Marvell Berlin bring-up codenames (`salami-proto`, `lexx`, `earth`, `steak`, `tyson`, `luther`) surfaced almost exclusively inside Marvell/Google GPL firmware tarballs and raw Widevine L1 keybox tables.

### 1.2 The Actual Multi-Generation Lineage (`board_config.h` & Widevine L1)

Directly observed in Google's GPL tree (`chromecast_sdk_oss/steak/bootloader/berlin_tools/bootloader/include/board_config.h`, `Copyright (C) 2012 Google, Inc.`, plus `berlin_config/configs/*.cfg` and `Cronick/WV-System-ID-Overview/Overview.csv`):

```c
#define BOARD_SALAMI_PROTO 1
#define BOARD_LEXX_B1      2
#define BOARD_LEXX_B2      3
#define BOARD_LEXX_B3      4
#define BOARD_LEXX_B4      5
#define BOARD_EARTH_B1     6
#define BOARD_EARTH_B2     7
#define BOARD_EARTH_B3     8
#define BOARD_EARTH_B4     9
/* NOTE: IDs 10..19 are omitted from the Chromecast Berlin drop */
#define BOARD_HENDRIX_B1  20
#define BOARD_HENDRIX_B3  21
#define BOARD_HENDRIX_B4  22
#define BOARD_LUTHER_B1   23
#define BOARD_LUTHER_B2   24
#define BOARD_LUTHER_B4   25
```

Combining `board_config.h`, `.cfg` board files, partition tables (`BOXINFO/V2/*.pt`), FCC filings, and Widevine L1 System IDs reconstructs the full naming pattern:

| Generation / Product | Regulatory Model | SDK / `board_config.h` IDs | Widevine L1 System ID (`Overview.csv`) | Verified Silicon & Hardware Diffs | Documented Developer Pun / Theme |
|---|---|---|---|---|---|
| **Chromecast 1 (2013)** | `H2G2-42` (PSU: `MST3K-US`) | `eureka` (`bg2cd_eureka_evt`), `anchovy` | `281` (`Eureka Dongle`) | Marvell `88DE3005` (`0x3005`, `BG2CD`, Cortex-A9), 512 MB RAM | *Hitchhiker's Guide to the Galaxy* (`H2G2-42`), *MST3K*, Syfy's *Eureka*, pizza topping (`anchovy`) |
| **BG2CDP Proto** | — | `salami-proto` (`1`) | — | `BG2CDP`, 512 MB, `BUTTON_GPIO 6`, `LED_WHITE 17`, `LED_RED 18` | Deli meat (`salami`) |
| **Pre-Prod G2** | — | `eureka-b1..b3` | `4239` / `4254` (`eureka-b3`) | `BG2CD` (`bg2cd_eureka_evt`) -> `BG2CDP` configs | Transitional Gen-1 to Gen-2 configs |
| **Gen-2 Era Boards** | `NC2-6A5` (2015), `NC2-6A5B` (2018) | `lexx-b1..b4` (`2..5`), `earth-b1..b4` (`6..9`) | `Lex/lexx-b4` (`5482`), `Earth/earth-b4` (`6311`) | Both `BG2CDP`, 512 MB, `BUTTON_GPIO 38`, `LED_WHITE 0`, `LED_RED 1` (`lexx` vs `earth` differ slightly in kernel/recovery NAND block offsets) | **Star Trek** saucer pun: `NC2`=`NCC` & `0x6A5`=`1701` (*USS Enterprise NCC-1701*); sci-fi series *LEXX* & *Earth*. **[UNCONFIRMED]:** Exact commercial mapping split between `lexx`, `earth`, Gen-2 Chromecast, and 2016 Google Home (`88DE3006`). |
| **Chromecast Audio (2015)** | `RUX-J42` | `hendrix-b1/b3/b4` (`20..22`) | — | `BG2CDP`, **256 MB**, `BUTTON_GPIO 36`, `AUD_MUTE_GPIO 5` (`hendrix-b3/b4.pt` symlink to `earth-b3/b4.pt`) | **Jimi Hendrix**: `RUX` (*Are You eXperienced*), `J-42` (*Midnight Lightning*) |
| **Chromecast Ultra (2016)** | `NC2-6A5-D` (`A4RNC2-6A5-D`) | SDK dir: **`steak`** · Platform: **`bg4cdp_tyson`** · Board: **`luther-b1/b2/b4` (`23..25`)** | **`Luther/luther-b4` (`6653`)** | **`MARVELL DE3009-A0`** (`0x3017`, `BG4CDP`), dual Cortex-A53 ARMv8, 512 MB `BOARD_MEM_SIZE`, `BUTTON_GPIO 41`, 256 MiB NAND | `-D` continues *Enterprise NCC-1701-D*; `lexx` (`2..5`) → `luther` (`23..25`) pairs **Lexx / Luthor**; `steak` + `tyson` pairs food/meat puns **[UNCONFIRMED: Tyson Foods vs. Neil deGrasse Tyson]** |
| **Home Displays / Speakers (2017–19)** | — | `joplin`, `biggie`, `caprica`, `estelle`, `newman`, `elaine` | `Caprica/caprica-b4` (`8198`), `Estelle/estelle-b4` (`8199`/`22197`), `Newman/newman-b4` (`10279`/`22188`), `Elaine` (`15475`) | Widevine L1 family sharing `-b4` suffix convention | Musicians (`joplin`, `biggie`), *BSG* (`caprica`), ***Seinfeld*** (`estelle`, `newman`, `elaine`) |

### 1.3 Developer Fingerprints Preserved in Shipped Code

Extracting comments, author strings, and `TODO` annotations inside `chromecast_sdk_oss/steak/` exposes the engineering constraints and team workflow behind `luther-b4`:

1. **`TODO(kolla)` in `bootloader/berlin_tools/bootloader/source/bootloader.c`:**
   - **Line 77:** `// disable crash counter. b/10478589.` — An internal Google Buganizer issue ID left in production source; `#define DISABLE_CRASH_COUNTER 1` suppresses automatic fallback to recovery after repeated boot crashes.
   - **Lines 539 & 547:** Inside `bootimg_hdr_verify()`:
     - USB branch: `/* TODO(kolla): Enable checks for ver, mkt_id etc.*/` — Non-secure bootloader enforces **only** `magic == 0xC0DE`, `code_type == 5`, and `userdata == 0xA33A`.
     - NAND branch: `/* TODO(kolla): Enable robust header checks for NAND image.*/`
   - **Line 618:** `/* TODO(kolla): Fix CUSTK, encryption of RSAK */` — Explains why the USB boot path copies `usb_extrsak_store` (`usb_key.h`) in front of `k_buff_img` while leaving the `CUSTK` slot (`1024 B` macro `USB_CUST_KSTORE_LEN`) zero-filled!
   - **Line 1445:**
     ```c
     /* TODO(kolla): This seem to be a result of statically linking libgcc.a,
      * one of the u-boot forums recommended locally defining this function.
      * Find cleaner fix.
      */
     void __aeabi_unwind_cpp_pr0(void) {}
     ```
2. **Other Google Cast & Marvell authors in the tree:**
   - `ghines`: `# TODO(ghines): only the size/offsets for block0, pre-bootloader, post-bootloader and trustzone matter...` (`BOXINFO/V2/lexx-b4.pt`, `bg2cdp_evt.nand.512M.linux.pt`).
   - `wzhong`: `# TODO(wzhong): use default gold linker.` (`bootloader/Makefile:379`).
   - `puru`: `/* TODO(puru): The original uboot code has many hardcoded buf sizes...` (`usb_storage.c:1319`).
   - Internal docs link leaked in kernel DTS headers (`berlin4cdp-dongle-nandpart-luther-b4.dtsi` and `-nandpart.dtsi`): `* go/cast-partition-map`.
   - `sign_image_cmd.sh`: Still contains `### HACK: FIXME ### SIGN_STORE_DIR=${SIGN_TOOL_DIR}/store_4cdp_z1`!
   - Marvell BSP engineers (`Hongjun Yuan <hyuan@marvell.com>`, `Jisheng Zhang <jszhang@marvell.com>`) authored `berlin4cdp*.dtsi` and `berlin-chipid.c`; Marvell bootloader failure print (`bootloader.c:1426`) reads `"tbdzz---- Img_Ld_And_Start error! Spinning now!\n"`.
   - **Mask ROM Descriptor Copy-Paste:** Although Ultra runs `BG4CDP` (`0x3017`) silicon, its internal Mask ROM USB string descriptor (`1286:8174`) was left verbatim as **`Product: "BG2CD S/N:12345678A"`**.

---

## 2. Silicon, Board & NAND Partition Ground Truth

### 2.1 Silicon Identification (Disproving Amlogic `S905D` & `88DE3218` Myths)

- **Package & Physical Teardown (IoE / EDN):**
  - SoC silk-screening: **`MARVELL DE3009-A0`** (`633ARTE TJ`).
  - RAM: Samsung **`K4F8E304HB-MGCH`** (8 Gbit LPDDR4-3200 package; `board_config.h` maps `BOARD_MEM_SIZE = 512 * 1024 * 1024` for `luther-b1/b2/b4`).
  - NAND Flash: Toshiba **`TC58NVG1S3HBAI6`** (2 Gbit = **256 MiB** SLC NAND, `2048 B` page, `128 KiB` erase block, `64 B` OOB per `luther-b4.cfg` `FLASH_TYPE=2048_128_64_536870912`).
  - Wireless SoC: **`MARVELL W8997-A0`** (802.11ac + BT, NXP `88W8997` lineage).
  - Power/Data Port: **Micro-USB** (bundled `A4RNC2-6A5-D` Ethernet-equipped PSU required for full 4K HDMI mode; USB-C did not appear until 2020 `Sabrina` Chromecast with Google TV).
- **Kernel SoC Table (`kernel/drivers/soc/berlin/berlin-chipid.c`):**
  ```c
  case 0x3005: soc_family = "Marvell Berlin BG2CD"; break;   // Chromecast 1
  case 0x3006: soc_family = "Marvell Berlin BG2CDP"; break;  // Chromecast 2 / Audio / HK Invoke
  case 0x3012: soc_family = "Marvell Berlin BG4DTV"; break;
  case 0x3017: soc_family = "Marvell Berlin BG4CDP"; break;  // Chromecast Ultra (DE3009-A0)
  case 0x3218: soc_family = "Marvell Berlin BG4CT"; break;   // Quad-core sibling (NOT Ultra)
  ```
- **CPU & OPP Table (`kernel/arch/arm64/boot/dts/marvell/berlin4cdp.dtsi` & `berlin4cdp-a0-dongle-common.dtsi`):**
  - **2 cores only:** `cpu@0` and `cpu@1`, `compatible = "arm,cortex-a53", "arm,armv8"`, `enable-method = "psci"`, OPPs `400 / 600 / 800 / 1000 / 1250 MHz`.
  - Boot cmdline (`chosen/bootargs`): `console=ttyS0,115200 console=ttyUSB0,115200 root=/dev/mtdblock7 rootfstype=squashfs root_part_name=rootfs`.

### 2.2 Exact `luther-b4` 256 MiB NAND Layout (`berlin4cdp-dongle-nandpart-luther-b4.dtsi`)

| Part # | Label | Start Block | Hex Offset | Blocks | Size | Notes |
|---:|---|---:|---:|---:|---:|---|
| 0 | `block0` | 0 | `0x00000` | 1 | `128 KiB` | Read-only; NAND geometry/attr |
| 1 | `prebootloader` | 1 | `0x20000` | 8 | `1 MiB` | Read-only; 8 copies (`bcm_erom` + `sysinit` + `tz_loader` + `drm_erom`) |
| 2 | `TZ` | 9 | `0x120000` | 24 | `3 MiB` | Read-only; production Trusty (`tw_en.bin`, `2,049,024 B`) |
| 3 | `TZ-B` | 33 | `0x420000` | 24 | `3 MiB` | Backup TrustZone slot |
| 4 | `postbootloader` | 57 | `0x720000` | 4 | `512 KiB` | Non-secure bootloader (`bootloader_en.bin`) |
| 5 | `postbootloader-B` | 61 | `0x7a0000` | 4 | `512 KiB` | Backup postbootloader |
| 6 | `kernel` (`boot.img`) | 65 | `0x820000` | 48 | `6 MiB` | Signed Android `ANDR` `mkbootimg` + LZ4/XZ kernel + DTB |
| 7 | `rootfs` | 113 | `0xe20000` | 752 | `94 MiB` | SquashFS (`/dev/mtdblock7`) |
| 8 | `cache` | 865 | `0x6c20000` | 1095 | `136.875 MiB` | Writable cache / OTA staging |
| 9 | `recovery` | 1960 | `0xf500000` | 74 | `9.25 MiB` | Recovery `boot.img` |
| 10 | `factory` | 2034 | `0xfe40000` | 8 | `1 MiB` | Factory calibration / keys |
| 11 | `fts` | 2042 | `0xff40000` | 3 | `384 KiB` | Flash TS key/value store (`bootloader.command`, etc.) |
| 12 | `bbt` | 2045 | `0xffa0000` | 3 | `384 KiB` | Bad block table (`2048` blocks = `256 MiB` exact) |

*(Note how earlier `luther-b1`/`luther-b2` configs had `KERNEL_BLK_START 81`, `FTS_BLK_START 2020`, `tw_en` `32` blocks; PVT/MP `luther-b4` tightened `TZ` to `24` blocks, shifted `kernel` to block `65`, and expanded `cache` to `1095` blocks.)*

---

## 3. Mask-ROM USB Protocol (`1286:8174`) & Binary Structure Forensics

### 3.1 Live USB Enumeration & Endpoint Oracle (`rom_window_capture2.txt`)

When cold-powered with the reset button held (`GPIO 41` active-low strap), the BG4CDP Mask ROM enumerates over Micro-USB as a High-Speed (`480 Mbps`) device (`VID:PID 1286:8174`, `bcdDevice=0.02`):

```text
Device Descriptor:     bDeviceClass=255 (0xff), bDeviceSubClass=254 (0xfe), bDeviceProtocol=255 (0xff)
Interface 0 (alt 0):   bInterfaceClass=255 (0xff), bInterfaceSubClass=254 (0xfe), bInterfaceProtocol=255 (0xff)
Device Qualifier:      bDeviceClass=255 (0xff), bDeviceSubClass=255 (0xff), bDeviceProtocol=255 (0xff)
Strings:               [1] "Marvell" | [2] "BG2CD S/N:12345678A" | [3] "S/N:12345678A" | [4] "DEFAULT"
Endpoints:             0x81 BULK IN (512B) | 0x01 BULK OUT (512B) | 0x02 INT OUT (512B) | 0x82 INT IN (512B)
```

**Observed Control & Interrupt Behavior (3 captured windows):**
- **EP0 Control Read Battery:** Standard `GET_STATUS(dev/if0/ep0-in)`, `GET_CONFIGURATION` (`0x01`), `GET_INTERFACE` (`0x00`), `GET_DESC(qualifier)`, and `GET_DESC(langid)` (`0x0409`) return valid data (`0–1 ms`). **`GET_DESC(BOS)`, `VENDOR_IN 0x00..0x0f`, `VENDOR_IN 0x20` (Amlogic probe), and `CLASS_IN 0x00..0x07` ALL immediately `STALL` (`0 ms`).**
- **Interrupt IN `0x82` Banner:** Emits an initial `0 B` ZLP, followed at `t+0.08s..0.14s` by a 28-byte image request packet:
  `69 2a 6d 2a 67 2a 72 2a 71 2a ff 62 63 6d 5f 65 72 6f 6d 2e 62 69 6e 2e 75 73 62 00`  
  = **`"i*m*g*r*q*\xffbcm_erom.bin.usb\0"`**
- **Idle Lifetime:** If the host stays silent after receiving the banner, the device disconnects at `t+1.67s..1.70s` (`ERR(5)`, kernel logs `usb 1-1: USB disconnect` followed by a failed `device descriptor read/all, error -71`).

### 3.2 Controlled USB Write Experiments (`erom_responder.log` & `erom_responder2.log`)

| Experiment / Mode | Payload Sent | Wire Behavior Observed | Interpretation |
|---|---|---|---|
| **A3700 WTP (`wtp-full`)** | `PREAMBLE(00d3022b)` (4B), `GETVERSION` (8B), `DATAHEADER(28672)` (12B), `DATA seq=2` (`8200 B`, total `8224 B`) | **Zero** WTP status responses on `0x82`/`0x81` (`TIMEOUT`); device immediately died at `seq=3` (`GONE @ t+0.31s`) | Proves BG4CDP Mask ROM does **not** implement Armada A3700 `WTP` protocol |
| **Raw `4 KB` sliced write (`13,312 B`, no ZLP)** | `bg2cdp_eureka_evt2/bcm_erom.bin` in `4 KB` writes w/ `5 ms` `0x82` poll after each slice | Slices `0..4096` and `4096..8192` succeeded; slice 3 at **`offset 8192`** failed with `ERR(5) [Errno 5] Input/Output Error` in `31 ms` | Either crossed an `8 KB` un-paced RX limit OR hit the `0xfe` header / wrong-chip rejection |
| **`8192 B + ZLP` (`clean8k`, `garbage8k` `0xAA`, `intprobe`, `twophase`, `fullchunk` `C0`)** | `8192 B` (`4096+4096`) + `0 B` ZLP on Bulk OUT `0x01` | **Window held alive for `5.33s–5.53s`** regardless of content (`0xAA` garbage acted identically to real bytes!); `0x82` answered polls with ZLPs; subsequent Bulk OUT (`[B]` or `[C1]`) **`TIMEOUT`ed (`4000 ms`)**; `1 B` INT OUT `0x02` (`intprobe`) succeeded but triggered no reply | **Critical finding:** Sending a ZLP at `8192 B` signals EOF on the USB transfer, stalling `0x01` and locking out `0x3400` (where the `0xC0DE` header and RSA signature actually reside!). `fullchunk` suffered this bug directly by sending `ZLP` after every `8 KB` chunk. |

### 3.3 The `coggy9/HKHacking` + `caramelkat/PodiumFlashing` Protocol Revelation

Cross-referencing community reverse-engineering of Marvell's official Berlin **`usb_boot`** host utility (from Harman Kardon Invoke, VID:PID `1286:8174`, `88DE3006`/`BG2CDP`) resolved how Marvell's host protocol works:

1. **Contiguous Bulk Transfers, Zero `4 KB` Chopping, Zero Mid-Stream ZLP:** `usb_boot` transmits images in **`0x100000` (1 MiB) contiguous bulk OUT blocks** on `0x01` (`bcm_erom` fits in a single transfer), waits ~1s after enumeration, and retries up to 3x because *"the first transfer after enumeration can fail"*.
2. **The `bDeviceSubClass` Branch (`0xff` vs. `0xfe`!):**
   - In `usb_boot.cpp`, `if (subclass == 0xff)` (`IROM_SUBCLASS`) sends raw `bcm_erom.bin.usb` **with NO 8-byte header**.
   - When **`subclass != 0xff`**, `usb_boot.cpp` enters its `i*m*g*r*q*` dispatch loop (`0x02` = `sysinit.img`, `0x03` = `bootloader.img`, `0x05` = `./drm_erom.img`, anything else `<NN>_IMAGE`) and **prepends an 8-byte little-endian header `[uint32(img_size), 0x00000000]`** on `0x01` before streaming the image!
   - **Crucial BG4CDP implication:** Because Ultra's Mask ROM reports **`bDeviceSubClass = 0xfe`** (`!= 0xff`) while sending `i*m*g*r*q*\xffbcm_erom.bin.usb\0`, **neither `usbboot-raw` (1 MiB single write, no header) nor `usbboot-hdr` (8-byte LE size header + 1 MiB single write) nor true EOF-only-ZLP `chunkpause` has ever been tested against Ultra's `1286:8174` window.**

### 3.4 Static Comparison of `bcm_erom.bin` Variants (`BG2CDP` vs. `BG4CDP`)

| Specimen | Size | MD5 | First 12 Bytes | Trailer / Keystore Architecture |
|---|---:|---|---|---|
| `PodiumFlashing` `bcm_erom.bin.usb` (`88DE3006`) | `24,576 B` | `d03b2d076117c3f635ce1ba68df73f8b` | `01000000 37c20013 01000000` | Same `BG2CDP` preamble format as `bg2cdp_eureka_evt2` |
| `steak-src` `bg2cdp_a0/bg2cdp_eureka_evt2` (`EVK`) | `13,312 B` | `5b368975934e87b4e1d8712617086d90` | `01000000 37c20013 01000000` | `BG2CDP` image format (was mistakenly served to BG4CDP Ultra on Oct 9) |
| `steak-src` `bg4cdp_z1/bg4cdp_tyson` (`Z1`) | `31,744 B` | `f11a2b95e6e9c8b3b61a885caf3d24e7` | `50000010 f2b3ed98 5c37bf1f` | Sparse pre-trailer tables (`0x0..0x104`, `0x814..0x918`, `0x2000..0x2d28`, `0x3028..0x344f`), `0xC0DE` @ `0x3404`, `256 B` RSA sig @ `0x3470..0x3570`, `16,624 B` encrypted body @ `0x3870..0x7960` |
| `steak-src` `bg4cdp_a0/bg4cdp_tyson` (`A0`) | `28,672 B` | `30939c7e193a31b85904b7abaa64313f` | `50000010 f2b3ed98 5c37bf1f` | Identical pre-trailer spans to `Z1`; `0x3400`: `00000020 dec00100...` (`-H 0x20000000`, `0xC0DE`), `wrapk` `6c437fe03f039a13c162ca23105a0251` @ `0x340c`, `256 B` RSA sig @ `0x3470..0x3570`, `14,144 B` encrypted body @ `0x3870..0x6fb0` |

*(Forensic note: Earlier `erom_static_analysis.py` runs flagged `0x0100` in `A0` as `"Thumb streak 60 <-- LOOKS LIKE CODE"`. Inspection proves `0x0104..0x0814` is all `0x00` padding, which ARM Thumb Capstone decodes as `0x0000` -> `movs r0, r0`. Filtering zero-instructions collapses `0x0100` from streak `60` to `2`.)*

---

## 4. TrustZone (`tw_en`), USB Mass-Storage Boot (`USBIMG`), and Proven Crypto Bounds

### 4.1 `BERLIN_BOOTINFO` OTP Map (`berlin_bootinfo.h`)

Boot state and fuses are exposed to non-secure code at physical address **`0x01f10000`** (`BERLIN_BOOTINFO`), containing `rsa_key_index:4`, `usb_boot_timeout:4`, `romkey_disable:1`, `disable_usb_boot:1`, `usb_disable_bootstrap:1`, `usb_disable_blank_media:1`, `usb_force_full_speed:1`, `usb_ignore_reset_tracker:1`, `otp_locked:1`, plus `aesk0_crc`, `rkek_crc`, `signk7_crc`, `mrvl_sign_right`, `cust_sign_right`, and source NAND block indices (`tsm`, `sysinit`, `erom`, `tz_loader`, `tz_kern`, `btld`).

*(Note: `luther-b4.cfg` sets `ROM_KEY_DISABLE=0` and `PRODUCTION_CHIP=0` for OSS build scripts; retail hardware enforces burned OTP bits on silicon.)*

### 4.2 Stage-3 `bootloader.c` USB Mass-Storage Boot (`USBIMG`)

Separate from the Stage-0 Mask ROM (`1286:8174`) USB *device* mode, `post-bootloader` (`bootloader.c`) implements a RAM-only **USB Mass-Storage host boot (`BOOTMODE_BOOTUSB`)** when `get_button_status()` sees `RA_Gbl_bootStrap bit 0 == 0`, or as a fallthrough if both primary `kernel` and `recovery` NAND images fail:

- **Raw Offset:** Reads contiguous `512 B` sectors starting at **`USB_BOOTIMG_START = 4096` (raw LBA 8)**—no partition table / filesystem required, and **zero writes to NAND** on failure (hangs until power-cycle).
- **RAM Staging:** `bootloader.c` copies `usb_extrsak_store` (`4,096 B` aligned in `k_buff`, `USB_EXT_RSAKSTORE_LEN 4096` on `luther-b4`, leaving the `CUSTK` `1,024 B` slot empty per `TODO(kolla)`), reads the USB image at `k_buff + 4096`, requires **`1 MiB <= reqd_buf_siz <= 32 MiB`**, checks ONLY three header fields in `bootimg_hdr_verify()`:
  - `+0x04`: `magic == 0xC0DE` (`-y 0` in `sign_image_v4`; **NOT** `0xbbc3` `-y 1` flasher magic)
  - `+0x07`: `code_type == 5` (`BCM_IMG_USBIMG_TYPE`)
  - `+0x0A`: `userdata == 0xA33A` (`CPU_IMG_USB_USRDATA`; NAND uses `0x0000`)
- **TrustZone Verification Gate:** Invokes **`tz_nw_verify_image(5, k_buff, MAX_ANDROID_IMG_SIZE, k_buff, &k_buff_size, 5)`** → `SMC_FUNC_TOS_CRYPTO_VERIFY_IMAGE` inside `tz_en` (`tw_en.bin`). Upon pass, expects a plaintext Android `ANDR` `mkbootimg` with LZ4 or XZ kernel + appended DTB + aligned ramdisk, forces `kernel_addr = CPU0_START_ADDR` and `second_addr = KERNEL_DTB_BUF`, appends `flash_ts.*`, and jumps.

### 4.3 Verified Cryptographic Bounds & Closed Dead Ends (`luther-b4`)

1. **`lexx-b4` → `luther-b4` Keystore Format Jump (`usb_key.h` vs. `sign_image_v4`):**
   - `lexx-b4`, `earth-b4`, and `hendrix-b4` embed a legacy **`792 B` `e1 a2`** `usb_extrsak_store` (`USB_EXT_RSAKSTORE_LEN 1024`).
   - `luther-b4` embeds a **`3,112 B` `02 8f`** `usb_extrsak_store` (`USB_EXT_RSAKSTORE_LEN 4096`, header `00000020 028f 8000 00000000 01000000 ffffffff 03ff2000`).
   - **`sign_image_v4` hard requirement:** Rejects `792 B` `e1 a2` stores with `rc=230 "invalid ext rsa keystore len:792"` (requires `> 0xc27` bytes; supports `02 8f` and an unpopulated magic `2f 04` with zero specimens in the SDK drop).
2. **`tw_en.bin` Identity Across `luther` Revisions:**
   - `luther-b2/tw_en.bin` and **`luther-b4/tw_en.bin` are MD5-identical** (`2,049,024 B`, MD5 `76a550ece00e5e8d74cd035f579c8e8c`, `@0x400`: `00000020 028f 0100 efff0000 01000000 ffffffff 03ff2000`).
   - Earlier `luther-b1/tw_en.bin` differs (`2,064,384 B`, MD5 `677787f45542a158b8c72adbdd47b9f8`, `00ff2000` field at `+0x414`).
3. **Closed Key-Extraction / Brute-Force Results (`store_pair.py`, `USB-FORGE-MATERIAL.md`):**
   - **Zero store key overlap:** Comparing `luther-b4`'s `3,112 B` `usb_extrsak_store` in 16-byte windows against `store_4cdp_z1/extrsa_sdk.store`, `lexx-b4`, `earth-b4`, `hendrix-b4`, and `store_cdp_a0` yields **`0` shared non-zero windows** (`243` shared windows on control comparison `store` ↔ `cdp_a0`).
   - **Keystores are DRM-engine-encoded (`customer_keystore_spec.h`):** Scanning `store_4cdp_z1/extrsa_sdk.store` (`028f`) against every endianness/component (`n`, `d`, `p`, `q`, `dp`, `dq`, `qinv`) of its paired private PEM (`store_4cdp_z1/extrsa_sdk_priv.pem`) yielded **zero plaintext matches**. The `.store` blobs wrap key context structures (`DRM_RSAKEYCTX1024_IN`, `DRM_SYMKEYCTX256_IN`, `OTP_PRV_KEY`) under hardware FIGO/DRMROM keys; **`luther`'s public modulus cannot be extracted from `usb_extrsak_store`.**
   - **Header DRBG & AES wrap scans:** Extra bytes in `sign_image_v4` headers come from deterministic `mv_simple_drbg` seeded by SHA-256 of the loaded store (not derived key material). Testing `wrapkey = AES-ECB(custkey, userkey)` and `AES-128-CBC(userkey, IV=0)` across **146 candidate keys** on production images and **467,502 candidates** against `tw_en.bin` produced **zero hits**.
4. **Isolated Remaining Empirical Probe (`USB_STICK_FINAL.img`):**
   - A format-valid `4 MiB` raw USB stick image (`sha256: 4914e0eebaf97616dc0257073426ac283af44c160d4fb7654738faf2e0535aea`, LBA 8 offset, `0xC0DE`, `codetype 5`, `0xA33A`, `1.51 MiB` reqd buffer, `store_4cdp_z1` PKCS#1v1.5 SHA-256 over `trailer[0:0x70]`) is already engineered and passes every NW check. Only **live execution against TOS `tz_nw_verify_image`** remains untested (since both TOS-reject and dummy-`ANDR`-reject hang identically without UART `ttyS0` / USB console `SMC_FUNC_SIP_USB_CONSOLE_PUT_CHAR` observation).

---

## 5. Runtime Network Telemetry, Omaha Oracle Results & Covert Side-Channel Proof

### 5.1 Live LAN Surface (`1.56.469779`) & Device Auth PKI

- **Port `8008` HTTP:** Unauthenticated `GET /setup/eureka_info?options=detail` (`eureka_full.json` at `options=65535`) returns build revision (`1.56.469779`), locale, timezone, opt-in flags, MAC/BSSID telemetry, `setup_state: 60`, and RSA-2048 device `public_key` (**no** OTA URL or `has_update` details leaked). `/apps/*` and `/setup/{ota,check_update,system_update,update,update_check}` return `404`; `/apps/Fling?page=sysupdate` (Gen-1 only) returns `404`; `/setup/offer` returns `403/405`.
- **Port `8009` Cast V2 (`ca=4101` = `0x1005` in mDNS `_googlecast._tcp`):** Frames length-prefixed `CastMessage` protobufs over TLS using Chromium's `CastTrustStore` two-root validation (`cast_cert_validator.cc`): sender issues `AuthChallenge` nonce (`urn:x-cast:com.google.cast.tp.deviceauth`), receiver signs `sender_nonce || peer_cert_der` (`RSASSA-PKCS1-v1_5` SHA-256) using the **SoC-fused Device Private Key**, and returns `client_auth_certificate` + per-generation `intermediate_certificate`.

### 5.2 Passive Sinkhole PCAP & Live Omaha Checkin Probing (`2026-10-11`)

- **210-second Passive Capture (`update_check_capture.pcapng`):** Under a blanket DNS NXDOMAIN sinkhole (`<ROUTER_SINKHOLE>`), the Ultra emitted **zero DNS queries** for Google OTA hosts—only connectivity-gated `connectivitycheck.gstatic.com/generate_204` probes failed (zero SNI, zero NTP). No silent background OTA check fires while offline-gated.
- **Unauthenticated Omaha Endpoint (`https://tools.google.com/service/update2` & `clients3.google.com/service/update2`):**
  - Submitting Gen-1 appid `{45ab3f62-be86-44be-9799-faa6a1229396}` (`GoogleTvEureka-0.1.0.0`) with `board="eureka-b3"` **still actively serves Gen-1 EOL `159268`** in 2026 (`91,055,663 B`, SHA-256 `9a6db04b3b8b46615a6763c54f7567d7fc1b5bc4036eb825dda1dd2febe489a7`, via `redirector.gvt1.com`).
  - **Board-keyed server filtering proven:** Every tested variation under `{45ab3f62-...}` (`luther`, `luther-b4`, `luther-pvt`, `luther-pvt-b`, `luther_pvt`, `luther-b4-pvt`, `luther-b3`, `steak`, `steak-b4`, `sparkle`, across `version="1.0.0.0"`, `"0"`, `"281626"`, `"1.56.281627"`) returned `<updatecheck status="noupdate"/>`.
  - **Gap identified:** Obtaining `ota.469779.stable-channel.luther-b4.<40HEX_SHA1>.zip` requires the Gen-2+/Ultra Omaha `appid` UUID (since `<40HEX>` is the exact SHA-1 of the served file, verified against live `282115` `gotham-pvt-a.bin` `4,163,944 B` on `edgedl.me.gvt1.com`, SHA-1 `214f6fe20f7b993046c77a9245c5805b056882dc`). The 5 GB `steak-src` OSS drop contains **zero** updater/Omaha strings (`update2`, `omaha`, `{45ab3f62...}`, `clients3.google.com` all absent).

### 5.3 Tested Media-Path Covert Exfiltration & Receiver State Findings (`1.56.469779`)

- **End-to-End Video Side-Channel (`dots/PROGRESS.md`, `2026-09-25`):**
  - Stock Ultra (`1.56.469779`) accepted an arbitrary local HTTP MP4 cast via Google's **Shaka Cast Demo Nightly (`07AEE832`)**.
  - Rendered 4K (`3840x2160`) encoded frames (`WIRE=690 B`, `WIRE_BITS=5520`, `dots-long.mp4`) through **Chromecast Ultra HDMI → PSVR passthrough (defeats HDCP) → HDMI↔USB-C 4K60 → dock → Elgato Cam Link 4K → `--stride 2` decode**, recovering **`60,000 B` (`md5 07727257fb36c10424e34772ab7aae48`, CRC `0x9E0E905B`) bit-identical** in ~26s (~1,230 captured frames). Proves an unprivileged optical/HDMI exfil channel already works end-to-end without firmware root once local execution reads data onto display surfaces.
- **Controller State & Widevine Behavior Observed Against Ultra (`2026-09-10`):**
  - Verified live `Supervisor` control-loss mechanism (`CastCast`): issuing `load()` during `PLAYING` wipes `_media_session_id` to `None` before `_try_load()` aborts, causing subsequent `STOP` commands to silently drop while media keeps playing; `EDIT_TRACKS_INFO` rejections (`INVALID_COMMAND`) still left UI active tracks updated optimistically.

---

## 6. Consolidated Ledger of Eliminated Hallucinations & False Paths

| Origin | False Claim / Path | Verification Disproving It | Ground Truth |
|---|---|---|---|
| **Google Neon** | Stadia *Injustice 2* & *DCUO* Lex Luthor green-and-purple warsuit ambient ads | Game catalog verification | Neither game was ever on Stadia; conflated from `luther` |
| **Google Neon** | `Marlin`/`Sailfish` + `NC2-6A5` Ultra IDs + "Lex Luthor" Voice Match bug | FCC filings & `board_config.h` | `NC2-6A5` = Gen 2; Ultra = `NC2-6A5-D`; `luther-b4` is in `board_config.h` |
| **Search AI** | Denied `lexx`/`earth`/`caprica` codenames; guessed `bcm` = Broadcom; `BG4CDP` = quad-core `88DE3218` | `board_config.h`, `usb_key.h`, `Overview.csv`, `berlin-chipid.c`, `berlin4cdp.dtsi` | `bcm` = Berlin Cryptographic Module; Ultra = `0x3017` `BG4CDP` (`DE3009-A0`, dual Cortex-A53) |
| **Aug–Oct 9 Sessions** | Ultra = Amlogic `S905D` / `GXL` (`1b8e:c003`) & Android TV U-Boot; `USB-C` power port | USB `1286:8174`, `DE3009-A0` teardown, Wikipedia spec table | Confused 2016 Marvell Ultra (`Micro-USB`) with 2020 Amlogic `Sabrina` (`USB-C`) |
| **Oct 12 USB Test** | Grafted Marvell Armada 3700 `wtp-a3700` protocol (`00d3022b`) onto `1286:8174` | `erom_responder2.log` (`GONE @ t+0.31s`) & `PodiumFlashing` | Berlin speaks `usb_boot` (`i*m*g*r*q*`), not Armada WTP |
| **Oct 13–17 Docs/Code** | Claimed `chunkpause` patched while omitting it; `fullchunk` sent per-chunk ZLPs; `sys_init_bg2cdp_z1` path typo | Code audit of `cc_erom_responder.py`, `runplan.env`, `erom_static_analysis.py` | Fixed in workspace: `usbboot-raw`, `usbboot-hdr`, EOF-only-ZLP `chunkpause`, & Z1/EVK paths now implemented and offline-verified |
| **USB Stick Draft 1** | Used `-y 1` (`0xbbc3`) for USB stick & tried old `792 B` `e1a2` keystores | `bootloader.c` + `sign_image_v4` (`rc=230`) | USB stick requires `-y 0` (`0xC0DE`), `0xA33A`, `028f` (`3,112 B` store) |
| **Oct 13 Static Script** | Flagged `0x0100` in `bcm_erom.bin` as `"Thumb streak 60 <-- LOOKS LIKE CODE"` | Non-zero byte span analysis of `A0` & `Z1` | `0x0104..0x0814` is `0x0000` padding decoded by Capstone as `movs r0, r0` |

---

## 7. Focused Analytical Questions for Neon

If ingesting this dossier for deeper inference or cross-referencing against public Android / Chromium / Marvell knowledge:

1. **Mask-ROM `0xfe` vs `0xff` State Machine:** On `BG2CDP` (`88DE3006`), `1286:8174` exposes `bDeviceSubClass = 0xff`, and `usb_boot` skips `0x82` / skips the 8-byte header (`withHeader=false`). On Ultra (`BG4CDP`), `1286:8174` exposes **`bDeviceSubClass = 0xfe`** *and* transmits `i*m*g*r*q*\xffbcm_erom.bin.usb\0` on `0x82`. Empirically, `8192 B + ZLP` keeps the ROM alive `~5.4s` (timing out further bulk OUT writes), whereas un-ZLP'd `4 KB` sliced writes with `5 ms` `0x82` probes hit `ERR(5)` at offset `8192`. Does Marvell `BG4CDP` Mask ROM expect: (a) an 8-byte LE length prefix `[len, 0]` because `bDeviceSubClass == 0xfe != 0xff`, (b) a single contiguous `1 MiB` bulk transfer without `4 KB` pauses/polls, or (c) true `8 KB` un-ZLP'd ring-buffer pacing (`chunkpause`)?
2. **`TODO(kolla)` Security Boundary Shift (`lexx-b4` → `luther-b4`):** Between `lexx-b4` (`792 B` `e1a2` keystore) and `luther-b4` (`3,112 B` `028f` keystore), Google left `bootimg_hdr_verify()`'s version/market-ID checks commented out as `TODO(kolla)` while upgrading TrustZone (`tw_en.bin`, `2,049,024 B`). Did TrustZone's `SMC_FUNC_TOS_CRYPTO_VERIFY_IMAGE` type-5 handler absorb full RSA-2048 (`usb_extrsak_store`), market-ID, and anti-rollback validation for `BOOT_SRC_USB` as well as `BOOT_SRC_NAND`?
3. **Missing Omaha `appid` & `board_config.h` IDs `10..19`:** What exact Omaha `{UUID}` did Google Cast Gen-2/Ultra (`luther-b4`, `GoogleTvEureka-0.1.0.0` or successor updater) query against `tools.google.com/service/update2`? And which Google Cast / Home devices occupied board IDs `10..19` between `BOARD_EARTH_B4 (9)` and `BOARD_HENDRIX_B1 (20)`?
