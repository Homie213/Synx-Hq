"""
Replix EXE Builder
==================
Step 1: Build Python server → dist-python/replix-server/replix-server.exe
Step 2: Build Electron app  → electron/dist/Replix-Setup-1.0.0.exe

Run:  python build_exe.py

Requirements:
  pip install pyinstaller
  npm install  (inside electron/ folder)
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).parent
DIST_PYTHON = ROOT / "dist-python"
ELECTRON_DIR = ROOT / "electron"


def run(cmd, cwd=None, check=True):
    print(f"\n>>> {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd or ROOT)
    if check and result.returncode != 0:
        print(f"ERROR: command failed with code {result.returncode}")
        sys.exit(result.returncode)
    return result.returncode == 0


def build_python():
    print("\n" + "="*60)
    print("STEP 1: Building Python server with PyInstaller")
    print("="*60)

    # Install PyInstaller if needed
    run("python -m pip install pyinstaller --quiet")

    # Clean previous build
    for d in [ROOT / "build", DIST_PYTHON]:
        if d.exists():
            shutil.rmtree(d)

    # Create spec content
    spec = f"""# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
ROOT = Path(r'{ROOT}')

a = Analysis(
    [str(ROOT / 'studio' / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'web'), 'web'),
        (str(ROOT / 'admin'), 'admin'),
        (str(ROOT / 'studio' / 'fonts'), 'studio/fonts'),
        (str(ROOT / 'data' / 'fonts'), 'data/fonts'),
    ],
    hiddenimports=[
        'studio.server', 'studio.db', 'studio.auth', 'studio.config',
        'studio.jobs', 'studio.live', 'studio.render', 'studio.media',
        'studio.ai', 'studio.brain', 'studio.license', 'studio.discord_log',
        'studio.health', 'studio.transcribe', 'studio.posting',
        'studio.creators', 'studio.accounts', 'studio.account',
        'studio.admin', 'studio.usage', 'studio.notices', 'studio.alerts',
        'studio.mailer', 'studio.ctx', 'studio.load', 'studio.updates',
        'studio.safe', 'studio.feedback', 'studio.profiles', 'studio.roman',
        'studio.storage',
        'sqlalchemy', 'sqlalchemy.dialects.sqlite', 'sqlalchemy.dialects.postgresql',
        'psycopg', 'uvicorn', 'fastapi', 'multipart',
        'PIL', 'numpy', 'httpx', 'anyio', 'anyio._backends._asyncio',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy'],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='replix-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(ROOT / 'electron' / 'assets' / 'icon.ico'),
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='replix-server',
)
"""
    spec_file = ROOT / "replix-server.spec"
    spec_file.write_text(spec, encoding="utf-8")

    # Create __main__.py for studio if it doesn't exist
    main_py = ROOT / "studio" / "__main__.py"
    if not main_py.exists():
        main_py.write_text(
            'from studio.server import main\nmain()\n',
            encoding="utf-8"
        )

    run(f"python -m PyInstaller replix-server.spec --distpath dist-python --workpath build/pyinstaller")
    print(f"\n✅ Python server built: {DIST_PYTHON / 'replix-server'}")


def copy_assets():
    print("\n" + "="*60)
    print("STEP 2: Copying assets")
    print("="*60)

    # Copy .env to dist
    env_src = ROOT / ".env"
    env_dst = DIST_PYTHON / ".env"
    if env_src.exists():
        shutil.copy2(env_src, env_dst)
        print("  Copied .env -> dist-python/.env")

    # Copy ico to electron/assets
    ico_src = ROOT / "replix.ico"
    ico_dst = ELECTRON_DIR / "assets" / "icon.ico"
    ico_dst.parent.mkdir(exist_ok=True)
    if ico_src.exists():
        shutil.copy2(ico_src, ico_dst)
        print("  Copied icon.ico")
    else:
        print(f"  WARNING: replix.ico not found at {ico_src}")

    print("[OK] Assets ready")


def build_electron():
    print("\n" + "="*60)
    print("STEP 3: Building Electron app")
    print("="*60)

    # Install npm deps
    run("npm install", cwd=ELECTRON_DIR)

    # Build
    run("npm run build:win", cwd=ELECTRON_DIR)

    output = ELECTRON_DIR / "dist"
    if output.exists():
        exes = list(output.glob("*.exe"))
        print("\n[OK] Electron EXE built!")
        for exe in exes:
            size_mb = exe.stat().st_size / (1024 * 1024)
            print(f"   {exe.name}  ({size_mb:.1f} MB)")
    else:
        print("WARNING: No dist folder found")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build Replix EXE")
    parser.add_argument("--python-only", action="store_true", help="Only build Python server")
    parser.add_argument("--electron-only", action="store_true", help="Only build Electron app")
    parser.add_argument("--assets-only", action="store_true", help="Only copy assets")
    args = parser.parse_args()

    if args.assets_only:
        copy_assets()
    elif args.python_only:
        build_python()
        copy_assets()
    elif args.electron_only:
        copy_assets()
        build_electron()
    else:
        build_python()
        copy_assets()
        build_electron()
