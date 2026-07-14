# Building the Scriptorium reader as a phone app (R5)

The reader is one Vite + React web app wrapped by [Capacitor](https://capacitorjs.com). The web
build (`dist/`) is bundled **inside** the APK and served from the local WebView — the reading path
makes zero network calls. The only network traffic is the shelf/sync connection to the bakery on your
LAN, which is plain HTTP and permitted through a scoped network-security-config (see
[Cleartext / LAN HTTP](#cleartext--lan-http)).

Everything below is Android. iOS is scaffolded (`ios/`) but deferred — see [iOS](#ios-deferred).

## Toolchain

| Tool | Version used | Notes |
| --- | --- | --- |
| JDK | 17 | Capacitor 7 / AGP 8.7 build on 17. `JAVA_HOME` must point at a JDK 17. |
| Node | 20+ (22 here) | |
| Android SDK | cmdline-tools + platform-tools | `ANDROID_HOME=~/Android/Sdk` |
| Compile/target SDK | **35** | `android/variables.gradle`; platform `android-35` installed. |
| Min SDK | 23 | Capacitor default. |
| Build tools | 35.0.0 | |
| Gradle | 8.11.1 (wrapper) | Downloaded automatically on first build. |
| Capacitor | 7.x | `@capacitor/{core,android,ios,filesystem,app,status-bar}` |

Install the SDK bits (once), accepting licenses:

```bash
export ANDROID_HOME=$HOME/Android/Sdk
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" \
  "platform-tools" "platforms;android-35" "build-tools;35.0.0"
```

## Build a debug APK

```bash
# from the repo root
just android-build
# or: cd reader && npm run android:build
```

That runs `vite build` → `cap sync android` → `./gradlew assembleDebug`. Output:

```
reader/android/app/build/outputs/apk/debug/app-debug.apk
```

It is signed with the standard Android **debug** keystore (`~/.android/debug.keystore`, auto-created) —
fine for sideloading, not for Play. Release signing / Play upload is out of scope (a later cycle).

### Pointing the app at your bakery

The bakery base URL is baked in at build time via `VITE_SERVER_URL` (see
`reader/src/shelf/client.ts`). The WebView origin is `https://localhost`, so a same-origin default
can't reach your LAN server — you must set it:

```bash
# Emulator (host loopback alias):
VITE_SERVER_URL=http://10.0.2.2:8720 just android-build

# Physical device on your Wi-Fi (use your i5 server's LAN IP):
VITE_SERVER_URL=http://192.168.1.10:8720 just android-build
```

Keep this host in sync with the network-security-config (below): the two must name the same host.

## Cleartext / LAN HTTP

Android blocks cleartext (`http://`) by default. Rather than a blanket
`android:usesCleartextTraffic="true"` (which would allow cleartext to the whole internet), we **deny
cleartext by default and allowlist only the bakery host** in
`android/app/src/main/res/xml/network_security_config.xml`:

```xml
<base-config cleartextTrafficPermitted="false" />
<domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="false">10.0.2.2</domain>       <!-- emulator -->
    <domain includeSubdomains="false">192.168.1.10</domain>   <!-- your bakery LAN IP -->
</domain-config>
```

Android's network-security-config **cannot express an RFC-1918 CIDR range** (e.g. `192.168.0.0/16`);
it allowlists concrete hosts. Because the bakery host is known at build time (`VITE_SERVER_URL`), we
simply list it. **When you change `VITE_SERVER_URL`, add/replace the matching `<domain>` here** or the
device will refuse the connection.

There is a *second*, independent gate: Chromium's **Mixed Content** policy blocks `http://` requests
made from an `https://` page — so with Capacitor's default `androidScheme: 'https'` the app (served
from `https://localhost`) can't reach the plain-HTTP bakery even when the OS permits cleartext. We
therefore set `server.androidScheme: 'http'` in `capacitor.config.ts`: the app loads from
`http://localhost` (still a secure context — `crypto.subtle` etc. work), and http→http to the LAN host
is not mixed content. The network-security-config remains the host allowlist.

## Install + run

```bash
# Emulator: start it (needs a system image + AVD — see below), then install.
$ANDROID_HOME/emulator/emulator -avd scriptorium_pixel -no-snapshot -gpu swiftshader_indirect &
adb wait-for-device
adb install -r reader/android/app/build/outputs/apk/debug/app-debug.apk
adb shell monkey -p com.scriptorium.reader 1   # launch

# Watch logs / the storage self-test result:
adb logcat | grep -i capacitor
```

Create the emulator AVD once (requires a system image — ~1 GB download):

```bash
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "system-images;android-36;google_apis;x86_64"
echo no | "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" \
  create avd -n scriptorium_pixel -k "system-images;android-36;google_apis;x86_64" -d pixel_6
```

### Storage self-test (on-device contract check)

Settings → **Storage self-test → Run** executes the shared `runStorageContract` against the real
`CapacitorStorage` backend and shows `PASS`/`FAIL`. This is the same contract MemoryStorage passes in
CI — it proves the `@capacitor/filesystem` backend is byte-faithful on the device.

### Offline / persistence checks

```bash
adb shell svc wifi disable && adb shell svc data disable   # or toggle airplane mode in the UI
# read / highlight / search — all must work with no network.
adb shell am force-stop com.scriptorium.reader             # kill
adb shell monkey -p com.scriptorium.reader 1               # relaunch → annotations + position intact
```

## iOS (deferred)

`npx cap add ios` has been run, so `ios/` holds an Xcode project — but it is **unpolished and deferred**
(DESIGN §2, Android-first). Building it requires **macOS** with Xcode + CocoaPods:

```bash
# on a Mac:
cd reader && npm install && npx cap sync ios && npx pod install --project-directory=ios/App
open ios/App/App.xcworkspace   # build/run from Xcode
```

On Linux, `cap add/sync ios` lays down/updates the project but skips `pod install` and `xcodebuild`.
