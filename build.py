#!/usr/bin/env python3
"""Patch Quest 1 v50 SystemUX.apk and wrap it in a Magisk module.

    python3 build.py SystemUX.apk [outdir]

Needs baksmali and smali on PATH. Every patch asserts its anchor text occurs
exactly once, so a different SystemUX build fails loudly instead of silently.
"""
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

VERSION = 7
MODULE_PROP = f"""id=systemux_dock
name=SystemUX accountless tweaks
version={VERSION}
versionCode={VERSION}
author=lucy
description=Customizable dock (pin any app, up to 10, no forced Meta apps) and an OCMS shim that serves locally installed apps to Library and Settings without a Meta account.
"""
UPDATE_BINARY = """#!/sbin/sh
umask 022
ui_print() { echo "$1"; }
OUTFD=$2
ZIPFILE=$3
. /data/adb/magisk/util_functions.sh
[ $MAGISK_VER_CODE -lt 20400 ] && abort "Please install Magisk v20.4+"
install_module
exit 0
"""

APP = "Lcom/oculus/library/model/App;"
OL = "Lcom/oculus/libraryapi/OVRLibrary;"
LA = "Lcom/oculus/vrshell/util/LibraryApiUtil;"
US = "Lcom/oculus/tablet/library/common/models/UnknownSource;"
DU = "Lcom/oculus/panelapp/anytimeui/utils/DynamicAppsUtil;"
UC = "Lcom/oculus/vrshell/util/UnknownSourcesUtil$Companion;"
MI = "Lcom/oculus/panelapp/library/models/LibraryAppTileContextMenuItem;"
VM = "Lcom/oculus/panelapp/library/LibraryViewModel;"
GK = "Lcom/oculus/common/gatekeepers/SystemUXDeviceConfig;"


def one(s, old, new):
    assert s.count(old) == 1, f"anchor found {s.count(old)} times: {old[:100]!r}"
    return s.replace(old, new)


def patch(root, rel, fn):
    p = root / rel
    s = p.read_text()
    p.write_text(fn(s))


# --- dock: force the hidden customization flags on ---------------------------
def device_config(s):
    head = """.method public static getBoolean(Landroid/content/Context;Lcom/oculus/deviceconfigclient/DeviceConfigMC;)Z
    .registers 5
"""
    inj = "".join(f"""
    sget-object v0, {GK}->{f}:{GK}
    if-eq p1, v0, :force_true
""" for f in ["AUI_BAR_CUSTOMIZATION", "AUI_BAR_CUSTOMIZATION_DRAG", "AUI_SHOW_UNKNOWN_SOURCES_IN_DYNAMIC_APP_BAR"])
    s = one(s, head, head + "    # ponytail-patch: force dock customization flags on" + inj)
    tail = """    move-result p0

    return p0
.end method

.method public static declared-synchronized getDebugCacheDumpString()"""
    return one(s, tail, tail.replace("    return p0\n", "    return p0\n\n    :force_true\n    const/4 v0, 0x1\n\n    return v0\n"))


# --- dock: pinned cap 5 -> 10, any app, no forced Meta apps ------------------
def dynamic_apps_vm(s):
    s = one(s, "    const/4 v2, 0x5\n\n    if-ne v1, v2, :cond_47", "    const/16 v2, 0xa\n\n    if-ne v1, v2, :cond_47")
    s = one(s, '    const/4 v0, 0x5\n\n    const-string v2, "aui_bar_apps_pinned"',
            '    const/16 v0, 0xa\n\n    const-string v2, "aui_bar_apps_pinned"')

    head = """.method private final buildBarAppItemFromPackageName(Ljava/lang/String;Ljava/lang/String;Z)Lcom/oculus/panelapp/anytimeui/bar/apps/BarAppItem;
    .registers 15
"""
    s = one(s, head, head + "\n    # ponytail-patch: always allow unknown sources\n    const/4 p3, 0x1\n")

    empty = """
    # ponytail-patch: no preinstalled apps forced on the bar
    new-instance v0, Ljava/util/LinkedHashMap;
    invoke-direct {v0}, Ljava/util/LinkedHashMap;-><init>()V
    return-object v0
"""
    for m in ("getDefaultPinnedApps", "getPermanentPinnedApps"):
        head = f".method private final {m}()Ljava/util/LinkedHashMap;\n    .registers 9\n"
        assert s.count(head) == 1, m
        i = s.index(head) + len(head)
        j = s.index(".end annotation\n", i) + len(".end annotation\n")
        s = s[:j] + empty + s[j:]

    skip = "".join(f"""
    const-string v3, "{pkg}"
    invoke-virtual {{v3, v2}}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v3
    if-nez v3, :goto_41
""" for pkg in ("com.oculus.explore", "com.oculus.store", "messenger_system_app", "share_system_app"))
    anchor = """    check-cast v2, Ljava/lang/String;

    const/4 v5, 0x0

    const/4 v6, 0x0

    const/4 v7, 0x4
"""
    return one(s, anchor, anchor.replace("    check-cast v2, Ljava/lang/String;\n",
                                         "    check-cast v2, Ljava/lang/String;\n    # ponytail-patch: drop preinstalled apps saved in the pinned list" + skip))


def cap_const(reg):
    return lambda s: one(s, f"    const/4 {reg}, 0x5\n", f"    const/16 {reg}, 0xa\n")


# --- library: pin menu for unknown sources, icons for local apps -------------
def library_app_utils(s):
    return one(s, ".method private static addPinOptionToMenu(", ".method public static addPinOptionToMenu(")


def library_content_adapter(s):
    B = "Lcom/oculus/library/model/App$Builder;"
    s = one(s, f"{US}ILandroid/view/View;)V\n    .registers 6\n", f"{US}ILandroid/view/View;)V\n    .registers 7\n")
    s = one(s, f"""    sget-object v1, {MI}->UNINSTALL:{MI}

    invoke-interface {{v0, v1}}, Ljava/util/List;->add(Ljava/lang/Object;)Z
""", f"""    sget-object v1, {MI}->UNINSTALL:{MI}

    invoke-interface {{v0, v1}}, Ljava/util/List;->add(Ljava/lang/Object;)Z

    # ponytail-patch: pin/unpin for unknown sources
    new-instance v1, {B}
    invoke-direct {{v1}}, {B}-><init>()V
    invoke-virtual {{p1}}, {US}->getPackageName()Ljava/lang/String;
    move-result-object v2
    invoke-virtual {{v1, v2}}, {B}->withPackageName(Ljava/lang/String;){B}
    const-string v2, "00000000"
    invoke-virtual {{v1, v2}}, {B}->withEntitlementHash(Ljava/lang/String;){B}
    invoke-virtual {{v1}}, {B}->build(){APP}
    move-result-object v1
    iget-object v2, p0, Lcom/oculus/panelapp/library/adapters/LibraryContentAdapter;->mViewModel:{VM}
    invoke-static {{v1, v2, v0}}, Lcom/oculus/panelapp/library/utils/LibraryAppUtils;->addPinOptionToMenu({APP}{VM}Ljava/util/List;)V
""")
    s = one(s, f"""    sget-object v0, {MI}->UNINSTALL:{MI}

    if-ne v0, p3, :cond_17
""", f"""    # ponytail-patch: handle pin/unpin for unknown sources
    sget-object v0, {MI}->PIN:{MI}
    const/4 v1, 0x1
    if-eq v0, p3, :pp_pin
    sget-object v0, {MI}->UNPIN:{MI}
    const/4 v1, 0x0
    if-ne v0, p3, :pp_not_pin
    :pp_pin
    invoke-virtual {{p1}}, {US}->getPackageName()Ljava/lang/String;
    move-result-object v0
    invoke-static {{v0, v1}}, Lcom/oculus/vrshell/util/AppStateUtil;->onPinnedAppStateShouldChange(Ljava/lang/String;Z)V
    const/4 v0, 0x0
    return-object v0
    :pp_not_pin

    sget-object v0, {MI}->UNINSTALL:{MI}

    if-ne v0, p3, :cond_17
""")
    FU = "Lcom/oculus/vrshell/util/FakeAppUtil;"
    FC = "Lcom/oculus/vrshell/util/FakeAppUtil$Companion;"
    TB = "Lcom/oculus/panelapp/library/databinding/LibraryAppTileBinding;"
    return one(s, """    :cond_4e
    sget-object v0, Lcom/oculus/vrshell/util/Q4BUtil;->Companion:Lcom/oculus/vrshell/util/Q4BUtil$Companion;
""", f"""    :cond_4e
    # ponytail-patch: icon from PackageManager for local apps
    sget-object v0, {FU}->Companion:{FC}
    invoke-virtual {{v0, p1}}, {FC}->isFromUnknownSource({APP})Z
    move-result v1
    if-eqz v1, :pp_not_local
    iget-object v1, p0, Lcom/oculus/panelapp/library/adapters/LibraryContentAdapter;->mContext:Landroid/content/Context;
    invoke-virtual {{v0, v1, p1}}, {FC}->getAppIconForUnknownPackage(Landroid/content/Context;{APP})Landroid/graphics/drawable/Drawable;
    move-result-object v0
    iget-object v1, p2, {TB}->imageView:Landroid/widget/ImageView;
    sget-object v3, Landroid/widget/ImageView$ScaleType;->FIT_CENTER:Landroid/widget/ImageView$ScaleType;
    invoke-virtual {{v1, v3}}, Landroid/widget/ImageView;->setScaleType(Landroid/widget/ImageView$ScaleType;)V
    invoke-virtual {{v1, v0}}, Landroid/widget/ImageView;->setImageDrawable(Landroid/graphics/drawable/Drawable;)V
    invoke-virtual {{p2, v2}}, {TB}->setImageAvailable(Z)V
    goto :goto_94
    :pp_not_local

    sget-object v0, Lcom/oculus/vrshell/util/Q4BUtil;->Companion:Lcom/oculus/vrshell/util/Q4BUtil$Companion;
""")


def library_vm_unknown_sources(s):
    s = one(s, "    .registers 3\n", "    .registers 8\n")
    return one(s, f"""    iget-object v0, p0, Lcom/oculus/panelapp/library/LibraryViewModel$3;->this$0:{VM}

    invoke-virtual {{v0, p1}}, {VM}->setUnknownSources(Ljava/util/List;)V
""", f"""    # ponytail-patch: local apps are served by the OCMS shim, keep this section empty
    iget-object v0, p0, Lcom/oculus/panelapp/library/LibraryViewModel$3;->this$0:{VM}
    new-instance v1, Ljava/util/ArrayList;
    invoke-direct {{v1}}, Ljava/util/ArrayList;-><init>()V
    invoke-virtual {{v0, v1}}, {VM}->setUnknownSources(Ljava/util/List;)V
""")


# --- OCMS shim ----------------------------------------------------------------
def ovr_library(s):
    s = one(s, f".method public getAllApps()[{APP}\n", f".method public getAllAppsOcms()[{APP}\n")
    s = one(s, f".method public getApp(Ljava/lang/String;){APP}\n", f".method public getAppOcms(Ljava/lang/String;){APP}\n")
    return s + f"""
# ponytail-patch: OCMS shim. Without a Meta account OCMS knows no apps, so answer
# with the locally installed (non-system) apps instead.
.method public getAllApps()[{APP}
    .registers 6

    invoke-virtual {{p0}}, {OL}->getAllAppsOcms()[{APP}
    move-result-object v0
    if-eqz v0, :local
    array-length v1, v0
    if-eqz v1, :local
    return-object v0

    :local
    iget-object v0, p0, {OL}->mContext:Landroid/content/Context;
    sget-object v1, Lcom/oculus/vrshell/util/UnknownSourcesUtil;->Companion:{UC}
    invoke-virtual {{v1, v0}}, {UC}->getUnknownSources(Landroid/content/Context;)Ljava/util/List;
    move-result-object v1
    invoke-interface {{v1}}, Ljava/util/List;->iterator()Ljava/util/Iterator;
    move-result-object v1
    new-instance v2, Ljava/util/ArrayList;
    invoke-direct {{v2}}, Ljava/util/ArrayList;-><init>()V
    new-instance v3, {DU}
    invoke-direct {{v3}}, {DU}-><init>()V

    :loop
    invoke-interface {{v1}}, Ljava/util/Iterator;->hasNext()Z
    move-result v4
    if-eqz v4, :done
    invoke-interface {{v1}}, Ljava/util/Iterator;->next()Ljava/lang/Object;
    move-result-object v4
    check-cast v4, {US}
    invoke-virtual {{v4}}, {US}->getPackageName()Ljava/lang/String;
    move-result-object v4
    invoke-virtual {{v3, v0, v4}}, {DU}->getAppForUnknownPackageName(Landroid/content/Context;Ljava/lang/String;){APP}
    move-result-object v4
    if-eqz v4, :loop
    invoke-interface {{v2, v4}}, Ljava/util/List;->add(Ljava/lang/Object;)Z
    goto :loop

    :done
    invoke-interface {{v2}}, Ljava/util/List;->size()I
    move-result v1
    new-array v1, v1, [{APP}
    invoke-interface {{v2, v1}}, Ljava/util/List;->toArray([Ljava/lang/Object;)[Ljava/lang/Object;
    move-result-object v1
    check-cast v1, [{APP}
    return-object v1
.end method

.method public getApp(Ljava/lang/String;){APP}
    .registers 5

    invoke-virtual {{p0, p1}}, {OL}->getAppOcms(Ljava/lang/String;){APP}
    move-result-object v0
    if-nez v0, :ret

    iget-object v1, p0, {OL}->mContext:Landroid/content/Context;
    :try_start
    invoke-virtual {{v1}}, Landroid/content/Context;->getPackageManager()Landroid/content/pm/PackageManager;
    move-result-object v2
    const/4 v3, 0x0
    invoke-virtual {{v2, p1, v3}}, Landroid/content/pm/PackageManager;->getApplicationInfo(Ljava/lang/String;I)Landroid/content/pm/ApplicationInfo;
    move-result-object v2
    :try_end
    .catch Ljava/lang/Exception; {{:try_start .. :try_end}} :ret

    iget v2, v2, Landroid/content/pm/ApplicationInfo;->flags:I
    and-int/lit8 v2, v2, 0x1
    if-nez v2, :ret
    new-instance v2, {DU}
    invoke-direct {{v2}}, {DU}-><init>()V
    invoke-virtual {{v2, v1, p1}}, {DU}->getAppForUnknownPackageName(Landroid/content/Context;Ljava/lang/String;){APP}
    move-result-object v0

    :ret
    return-object v0
.end method
"""


def library_api_util(s):
    m = re.search(r"\.method public static getApplications_BLOCKING\(Landroid/content/Context;\)Ljava/util/List;.*?\.end method\n", s, re.S).group(0)
    raw = m.replace("getApplications_BLOCKING(", "getOcmsApplications_BLOCKING(").replace(f"{OL}->getAllApps()", f"{OL}->getAllAppsOcms()")
    assert raw.count("getAllAppsOcms") == 1
    return s + "\n\n# ponytail-patch: raw OCMS list (bypasses the shim) for unknown-sources detection\n" + raw


def unknown_sources_util(s):
    return one(s, f"{LA}->getApplications_BLOCKING(", f"{LA}->getOcmsApplications_BLOCKING(")


PATCHES = [
    ("smali_classes", "com/oculus/common/deviceconfig/DeviceConfigHelper.smali", device_config),
    ("smali_classes", "com/oculus/panelapp/anytimeui/bar/apps/DynamicAppsViewModel.smali", dynamic_apps_vm),
    ("smali_classes", "com/oculus/panelapp/anytimeui/bar/apps/DynamicAppsViewModel$initializeAppStateBroadcaster$1.smali", cap_const("v5")),
    ("smali_classes", "com/oculus/panelapp/anytimeui/bar/apps/DynamicAppsViewModel$initializeAppStateObserver$1.smali", cap_const("v0")),
    ("smali_classes", "com/oculus/libraryapi/OVRLibrary.smali", ovr_library),
    ("smali_classes", "com/oculus/vrshell/util/LibraryApiUtil.smali", library_api_util),
    ("smali_classes2", "com/oculus/panelapp/library/utils/LibraryAppUtils.smali", library_app_utils),
    ("smali_classes2", "com/oculus/panelapp/library/adapters/LibraryContentAdapter.smali", library_content_adapter),
    ("smali_classes2", "com/oculus/panelapp/library/LibraryViewModel$3.smali", library_vm_unknown_sources),
    ("smali_classes2", "com/oculus/vrshell/util/UnknownSourcesUtil$Companion.smali", unknown_sources_util),
]


def repack(src, dst, repl):
    """Copy an APK replacing entries, keeping compression and zipalign -p alignment.
    The original v1 signature stays: system-partition APKs only have the
    AndroidManifest.xml digest checked on Android 10, and that entry is untouched."""
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w") as zo:
        for info in zi.infolist():
            data = Path(repl[info.filename]).read_bytes() if info.filename in repl else zi.read(info)
            ni = zipfile.ZipInfo(info.filename, info.date_time)
            ni.compress_type, ni.external_attr = info.compress_type, info.external_attr
            if ni.compress_type == zipfile.ZIP_STORED:
                align = 4096 if info.filename.endswith(".so") else 4
                off = zo.fp.tell() + 30 + len(ni.filename.encode())
                ni.extra = b"\0" * (-off % align)
            zo.writestr(ni, data)


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    apk = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2] if len(sys.argv) == 3 else "build").resolve()
    work = out / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    with zipfile.ZipFile(apk) as z:
        for d in ("classes", "classes2"):
            (work / f"{d}.dex").write_bytes(z.read(f"{d}.dex"))
            subprocess.run(["baksmali", "d", str(work / f"{d}.dex"), "-o", str(work / f"smali_{d}")], check=True)

    for tree, rel, fn in PATCHES:
        patch(work / tree, rel, fn)
        print("patched", rel)

    repl = {}
    for d in ("classes", "classes2"):
        dex = work / f"{d}.patched.dex"
        # -j 1: multi-threaded smali output is not byte-reproducible
        subprocess.run(["smali", "a", "-j", "1", "-a", "29", str(work / f"smali_{d}"), "-o", str(dex)], check=True)
        repl[f"{d}.dex"] = dex

    patched_apk = out / "SystemUX.apk"
    repack(apk, patched_apk, repl)

    module = out / f"systemux_dock-v{VERSION}.zip"
    with zipfile.ZipFile(module, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/com/google/android/update-binary", UPDATE_BINARY)
        z.writestr("META-INF/com/google/android/updater-script", "#MAGISK\n")
        z.writestr("module.prop", MODULE_PROP)
        z.writestr("system/priv-app/SystemUX/.replace", "")
        z.write(patched_apk, "system/priv-app/SystemUX/SystemUX.apk")
    print("built", patched_apk, "and", module)


if __name__ == "__main__":
    main()
