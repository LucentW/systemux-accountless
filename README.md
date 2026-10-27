# SystemUX accountless tweaks (Quest 1, v50)

Magisk module that patches `SystemUX.apk` on a Quest 1 running the last
firmware (`50.0.0.198.257`) used without a Meta account:

- **Dock**: enables the hidden bar customization flags, lets any app (sideloaded
  included) be pinned from the Library menu, raises the pinned-app cap from 5 to
  10 and stops forcing Explore, Store, Messenger/People and Share onto the bar.
- **OCMS shim**: `OVRLibrary.getAllApps()`/`getApp()` fall back to the locally
  installed (non-system) apps when OCMS returns nothing, so Library, app
  permissions, App Lock, notifications and storage pages work without an
  account. Library tiles of local apps use the package icon, and the separate
  "Unknown Sources" section (with its warning) is kept empty.

Not included: more than 3 multitasking windows. That layout is hard-coded in
VrShell's native `libshell.so`.

## Build

Needs `python3`, `baksmali`, `smali`. The original APK is not part of this repo:

```sh
adb pull /system/priv-app/SystemUX/SystemUX.apk
python3 build.py SystemUX.apk          # -> build/SystemUX.apk, build/systemux_dock-v7.zip
```

Every patch checks that its anchor occurs exactly once, so another SystemUX
build fails at patch time rather than on the headset.

## Install / remove

Install the zip from the Magisk app (Modules → Install from storage). The
patched APK keeps the original v1 signature: on Android 10 system-partition
APKs only get the `AndroidManifest.xml` digest checked, and that entry is
untouched.

To undo: `adb shell su -c "touch /data/adb/modules/systemux_dock/disable"`
(or remove that directory), then reboot. adb keeps working even if the shell UI
breaks.
