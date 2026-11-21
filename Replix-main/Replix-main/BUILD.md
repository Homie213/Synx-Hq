# Building Replix EXE

## Quick Build (Full EXE)
```
python build_exe.py
```
Output: `electron/dist/Replix-Setup-1.0.0.exe`

## Step by Step

### 1. Requirements
```
pip install pyinstaller
cd electron && npm install
```

### 2. Build Python server only
```
python build_exe.py --python-only
```

### 3. Build Electron EXE only (after Python is built)
```
python build_exe.py --electron-only
```

## Auto-Update Setup (GitHub)

1. Create GitHub repo: `YOUR_USERNAME/replix`
2. Update `electron/package.json`:
   ```json
   "publish": {
     "provider": "github",
     "owner": "YOUR_USERNAME",
     "repo": "replix"
   }
   ```
3. Create GitHub token with `repo` scope
4. Set env: `GH_TOKEN=your_token`
5. Build: `python build_exe.py`
6. Create GitHub Release with the generated `.exe`

## How Auto-Update Works
- App checks GitHub Releases every 4 hours
- Downloads new version silently in background
- Shows "Update ready" dialog to user
- User clicks "Restart and update" → installs

## HWID Binding
- Each machine gets a unique HWID based on: hostname, username, CPU, platform
- When user activates a key, HWID is stored in Supabase
- Same key on different machine → blocked ("device is taken")
- Admin can unlink a device from admin panel → user can activate on new machine

## File Structure
```
electron/
  src/
    main.js      ← Electron main process
    preload.js   ← IPC bridge (safe API to web app)
    splash.html  ← Loading screen
  assets/
    icon.ico     ← App icon
  package.json   ← Electron config + build config
  dist/          ← Built EXE goes here

dist-python/
  replix-server/ ← PyInstaller output (bundled Python)
```
