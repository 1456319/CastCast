<!-- [KEY 0] Agent Jules: File verified structurally sound. -->
# Milestone 1 Outline (MVP)

This document outlines the state of the VideoQualityCheckerApp at Milestone 1, where the Termux root automation successfully orchestrates the unprivileged Capacitor frontend commanding a root daemon, configures Termux, securely delegates Android system permissions, and launches an isolated Python/FFmpeg backend that controls a Chromecast on the local network.

## Current State & Manual ADB Requirements
To achieve this milestone, a few steps had to be executed manually on the test device via ADB. If a brand-new user downloaded the APK right now, they would be missing the following:

1. **The Python Backend Code (`daemon/`):** 
   The Capacitor APK doesn't actually bundle the Python backend codebase. I had to manually use `adb push` to copy the `daemon/` directory from the repository into `/storage/emulated/0/Download/VideoQualityCheckerApp/` on the device.
2. **Directory Structure:** 
   I manually ran `mkdir` to create the `Chromecast/` and `Chromecast/.castcast/` directories on the phone.
3. **Termux Permissions:** 
   I manually ran `appops` to grant Termux the "Display over other apps" and "All files access" permissions. 
   *(Note: As of the final Milestone 1 commit, the root payload in `TermuxDaemonPlugin.java` now automates this step entirely using `su`, so this specific step is already resolved for future installs!)*

## Next Steps: Automating the MVP
To make this a true 1-click install MVP that *anyone* with a rooted phone and Termux can use, we need the APK to bundle and provision its own backend. 

Here is the exact plan to automate the remaining manual steps:

1. **Bundle the Backend:** 
   We will configure the web build script (`package.json`) to copy the entire `daemon/` folder into the `dist/` folder right before building. This packages the backend directly inside the APK's web assets.
2. **Auto-Extraction:** 
   We will add a Java function to `TermuxDaemonPlugin.java` that runs on launch. It will check if `/storage/emulated/0/Download/VideoQualityCheckerApp/daemon/` exists. If it doesn't, it will automatically copy the backend out of the APK's assets and place it onto the phone's shared storage.
3. **Auto-Directory Creation:** 
   The same Java function will verify and automatically create the `Chromecast/` and `Chromecast/trash/` queue directories so the user doesn't have to manually build the folder structure.
