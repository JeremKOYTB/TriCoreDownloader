import os
import re
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

base_dir = os.path.abspath(SPECPATH)
config_path = os.path.join(base_dir, "TriCoreDownloader", "config.py")

if not os.path.isfile(config_path):
    raise FileNotFoundError(f"Fichier introuvable : {config_path}")

with open(config_path, "r", encoding="utf-8") as f:
    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', f.read())

if not match or not match.group(1).strip():
    raise RuntimeError("APP_VERSION introuvable ou vide dans TriCoreDownloader/config.py")

app_version = match.group(1).strip().lstrip("v")

datas = []
candidate_datas = [
    ("TriCoreDownloader/titles_cafe.json", "TriCoreDownloader"),
    ("TriCoreDownloader/Songs", "TriCoreDownloader/Songs"),
    ("TriCoreDownloader/Songs", "Songs"),
    ("TriCoreDownloader/Languages", "TriCoreDownloader/Languages"),
    ("icons", "icons"),
    ("icons/TriCoreDownloader.png", "TriCoreDownloader"),
]
if sys.platform == "darwin":
    candidate_datas.append(("icons/TriCoreDownloader.Apple.svg", "icons"))

for src_rel, dst_rel in candidate_datas:
    src_abs = os.path.join(base_dir, src_rel)
    if os.path.exists(src_abs):
        datas.append((src_rel, dst_rel))

binaries = []
hiddenimports = [
    "netifaces2",
    "darkdetect",
    "PyQt6.QtSvg",
    "PyQt6.QtMultimedia",
    "Updater",
]

for pkg in ("cryptography", "pyctr", "py7zr", "certifi"):
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass

try:
    hiddenimports += collect_submodules("TriCoreDownloader.Languages")
except Exception:
    pass

excludes = [
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtQml",
    "PyQt6.QtQuick",
    "PyQt6.QtQuickWidgets",
    "PyQt6.Qt3DCore",
    "PyQt6.QtBluetooth",
    "PyQt6.QtPositioning",
    "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets",
    "PyQt6.QtDBus",
    "PyQt6.QtDesigner",
    "PyQt6.QtHelp",
    "PyQt6.QtNfc",
    "PyQt6.QtOpenGL",
    "PyQt6.QtOpenGLWidgets",
    "PyQt6.QtRemoteObjects",
    "PyQt6.QtSensors",
    "PyQt6.QtSerialPort",
    "PyQt6.QtSql",
    "PyQt6.QtTest",
    "PyQt6.QtXml",
    "tkinter",
    "unittest",
    "pydoc",
]


def resolve_icon(candidates):
    for c in candidates:
        p = os.path.join(base_dir, c)
        if os.path.isfile(p):
            return p
    return None


if sys.platform == "win32":
    icon_path = resolve_icon(["icons/TriCoreDownloader.ico", "TriCoreDownloader.ico"])
elif sys.platform == "darwin":
    icon_path = resolve_icon(["icons/TriCoreDownloader.icns", "TriCoreDownloader.icns"])
else:
    icon_path = resolve_icon(["icons/TriCoreDownloader.png", "TriCoreDownloader.png"])

win_version_info = None
if sys.platform == "win32":
    try:
        from PyInstaller.utils.win32.versioninfo import (
            VSVersionInfo,
            FixedFileInfo,
            StringFileInfo,
            StringTable,
            StringStruct,
            VarFileInfo,
            VarStruct,
        )

        digits = [int(n) for n in re.findall(r"\d+", app_version)][:4]
        while len(digits) < 4:
            digits.append(0)
        t_ver = tuple(digits)
        s_ver = ".".join(str(n) for n in digits)

        win_version_info = VSVersionInfo(
            ffi=FixedFileInfo(
                filevers=t_ver,
                prodvers=t_ver,
                mask=0x3F,
                flags=0x0,
                OS=0x40004,
                fileType=0x1,
                subtype=0x0,
                date=(0, 0),
            ),
            kids=[
                StringFileInfo(
                    [
                        StringTable(
                            "040904B0",
                            [
                                StringStruct("CompanyName", "JeremKO"),
                                StringStruct("FileDescription", "TriCoreDownloader"),
                                StringStruct("FileVersion", s_ver),
                                StringStruct("InternalName", "TriCoreDownloader"),
                                StringStruct("LegalCopyright", "JeremKO"),
                                StringStruct("OriginalFilename", "TriCoreDownloader.exe"),
                                StringStruct("ProductName", "TriCoreDownloader"),
                                StringStruct("ProductVersion", s_ver),
                            ],
                        )
                    ]
                ),
                VarFileInfo([VarStruct("Translation", [1033, 1200])]),
            ],
        )
    except Exception:
        win_version_info = None

a = Analysis(
    [os.path.join(base_dir, "run_TriCoreDownloader.py")],
    pathex=[base_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

if sys.platform == "win32":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="TriCoreDownloader",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        version=win_version_info,
        icon=[icon_path] if icon_path else None,
    )
elif sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="TriCoreDownloader",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity="-",
        entitlements_file=None,
        icon=[icon_path] if icon_path else None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="TriCoreDownloader",
    )
    app = BUNDLE(
        coll,
        name="TriCoreDownloader.app",
        icon=icon_path,
        bundle_identifier="com.jeremko.tricoredownloader",
        info_plist={
            "CFBundleDisplayName": "TriCoreDownloader",
            "CFBundleName": "TriCoreDownloader",
            "CFBundleShortVersionString": app_version,
            "CFBundleVersion": app_version,
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="TriCoreDownloader",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=[icon_path] if icon_path else None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="TriCoreDownloader",
    )
