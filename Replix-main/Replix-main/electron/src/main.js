/**
 * Replix Desktop — Main Electron Process
 *
 * Security model:
 * - EXE contains NO secrets (no DB password, no API keys, no webhooks)
 * - App connects to Render-hosted server (REPLIX_SERVER_URL)
 * - In dev mode: connects to local Python server
 * - ASAR is encrypted (see package.json asarUnpack + electron-builder config)
 * - Code is obfuscated in production build
 */
const { app, BrowserWindow, ipcMain, shell, Tray, Menu, nativeImage, dialog } = require('electron');
const { autoUpdater } = require('electron-updater');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const https = require('https');
const os = require('os');
const crypto = require('crypto');
const fs = require('fs');

// ---------------------------------------------------------------- config
const IS_DEV = process.argv.includes('--dev') || !app.isPackaged;
const LOCAL_PORT = 8765;

// In production: use Render server. In dev: use local Python
const SERVER_URL = IS_DEV
  ? `http://127.0.0.1:${LOCAL_PORT}`
  : (process.env.REPLIX_SERVER_URL || 'https://replix-w5v1.onrender.com');

const BASE_URL = SERVER_URL;

// ---------------------------------------------------------------- HWID (machine fingerprint)
function getHWID() {
  const parts = [
    os.hostname(),
    os.userInfo().username,
    os.cpus()[0]?.model || '',
    os.platform(),
    os.arch(),
  ];
  return crypto.createHash('sha256').update(parts.join('|')).digest('hex');
}

// ---------------------------------------------------------------- Python server (DEV ONLY)
let pythonProc = null;

function startPythonServer() {
  if (!IS_DEV) return Promise.resolve(); // Production uses Render server

  return new Promise((resolve, reject) => {
    const cwd = path.join(__dirname, '..', '..');
    const env = {
      ...process.env,
      REPLIX_PORT: String(LOCAL_PORT),
      REPLIX_HOST: '127.0.0.1',
      REPLIX_PUBLIC_URL: BASE_URL,
      REPLIX_ACCOUNTS: '1',
      REPLIX_HWID: getHWID(),
      REPLIX_DESKTOP: '1',
    };

    pythonProc = spawn('python', ['-m', 'studio.server'], { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] });
    pythonProc.stdout.on('data', d => console.log('[PY]', d.toString().trim()));
    pythonProc.stderr.on('data', d => console.error('[PY ERR]', d.toString().trim()));
    pythonProc.on('error', reject);

    let attempts = 0;
    const poll = setInterval(() => {
      attempts++;
      http.get(`${BASE_URL}/healthz`, res => {
        if (res.statusCode === 200) { clearInterval(poll); resolve(); }
      }).on('error', () => {
        if (attempts >= 60) { clearInterval(poll); reject(new Error('Server start timeout')); }
      });
    }, 500);
  });
}

function stopPythonServer() {
  if (pythonProc) {
    if (process.platform === 'win32') spawn('taskkill', ['/pid', String(pythonProc.pid), '/f', '/t']);
    else pythonProc.kill('SIGTERM');
    pythonProc = null;
  }
}

// ---------------------------------------------------------------- Check server reachable (production)
function waitForServer(maxWait = 60000) {
  if (IS_DEV) return startPythonServer();

  return new Promise((resolve, reject) => {
    const start = Date.now();
    const url = new URL(BASE_URL + '/healthz');
    const mod = url.protocol === 'https:' ? https : http;

    const check = () => {
      const req = mod.get(url.href, { timeout: 10000 }, res => {
        if (res.statusCode === 200) return resolve();
        if (Date.now() - start > maxWait) return reject(new Error('Server returned status ' + res.statusCode));
        setTimeout(check, 2500);
      });
      req.on('timeout', () => {
        req.destroy();
      });
      req.on('error', (err) => {
        if (Date.now() - start > maxWait) return reject(new Error('Cannot reach Replix server: ' + err.message));
        setTimeout(check, 2500);
      });
    };
    check();
  });
}

// ---------------------------------------------------------------- windows
let mainWindow = null;
let tray = null;
let splashWindow = null;

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 400, height: 280,
    frame: false, transparent: true,
    resizable: false, center: true, alwaysOnTop: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280, height: 820,
    minWidth: 900, minHeight: 600,
    show: false,
    backgroundColor: '#0A0106',
    autoHideMenuBar: true,
    icon: path.join(__dirname, '..', 'assets', 'icon.ico'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      // Security hardening
      sandbox: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  });

  Menu.setApplicationMenu(null);

  // Inject HWID + desktop flag on every page load
  mainWindow.webContents.on('did-finish-load', () => {
    mainWindow.webContents.executeJavaScript(
      `window.__REPLIX_HWID__ = ${JSON.stringify(getHWID())}; window.__REPLIX_DESKTOP__ = true;`
    ).catch(() => {});
  });

  // Inject x-replix-desktop header on every request
  mainWindow.webContents.session.webRequest.onBeforeSendHeaders((details, callback) => {
    details.requestHeaders['x-replix-desktop'] = '1';
    details.requestHeaders['x-replix-hwid'] = getHWID();
    callback({ requestHeaders: details.requestHeaders });
  });

  // Open external links in system browser, not Electron
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.includes('/oauth/') || !url.startsWith(SERVER_URL)) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  // Block navigation to unknown origins or OAuth flows
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (url.includes('/oauth/') || (!url.startsWith(SERVER_URL) && !url.startsWith('http://127.0.0.1'))) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  mainWindow.on('close', e => {
    if (!app.isQuitting) { e.preventDefault(); mainWindow.hide(); }
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  return mainWindow;
}

function createTray() {
  const iconPath = path.join(__dirname, '..', 'assets', 'icon.ico');
  const icon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
  tray = new Tray(icon);
  tray.setToolTip('Replix');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open Replix', click: () => { mainWindow?.show(); mainWindow?.focus(); } },
    { type: 'separator' },
    { label: 'Quit', click: () => { app.isQuitting = true; app.quit(); } },
  ]));
  tray.on('double-click', () => { mainWindow?.show(); mainWindow?.focus(); });
}

// ---------------------------------------------------------------- auto-updater
function setupAutoUpdater() {
  if (IS_DEV) return;
  try {
    autoUpdater.autoDownload = true;
    autoUpdater.autoInstallOnAppQuit = true;
    autoUpdater.setFeedURL({
      provider: 'generic',
      url: `${BASE_URL}/api/desktop/updates`,
    });
    autoUpdater.on('checking-for-update', () => console.log('[Updater] Checking for updates at:', `${BASE_URL}/api/desktop/updates`));
    autoUpdater.on('update-available', info => {
      console.log('[Updater] Update available:', info?.version);
      mainWindow?.webContents.send('update-available', info);
    });
    autoUpdater.on('download-progress', progressObj => {
      mainWindow?.webContents.send('update-download-progress', progressObj);
    });
    autoUpdater.on('update-not-available', info => console.log('[Updater] App is up to date:', info?.version));
    autoUpdater.on('update-downloaded', info => {
      console.log('[Updater] Update downloaded:', info?.version);
      mainWindow?.webContents.send('update-downloaded', info);
    });
    autoUpdater.on('error', err => console.error('[Updater Error]', err.message));
    autoUpdater.checkForUpdates().catch(err => console.error('[Updater Check Failed]', err));
    // Check every 10 minutes continuously
    setInterval(() => autoUpdater.checkForUpdates().catch(() => {}), 10 * 60 * 1000);
  } catch (err) {
    console.error('[Updater setup error]', err);
  }
}

// ---------------------------------------------------------------- IPC
ipcMain.on('check-for-updates', () => {
  if (!IS_DEV) autoUpdater.checkForUpdates().catch(() => {});
});
ipcMain.on('install-update', () => { app.isQuitting = true; autoUpdater.quitAndInstall(); });
ipcMain.handle('get-hwid', () => getHWID());
ipcMain.handle('open-folder', async (_, folderPath) => {
  let target = folderPath;
  if (!target || !fs.existsSync(target)) {
    target = path.join(app.getPath('userData'), 'data');
  }
  try {
    if (!fs.existsSync(target)) {
      fs.mkdirSync(target, { recursive: true });
    }
    shell.openPath(target);
  } catch (err) {
    console.error('[Open folder error]', err);
  }
});
ipcMain.handle('open-external', async (_, url) => {
  if (url && (url.startsWith('https://') || url.startsWith('http://'))) {
    shell.openExternal(url);
  }
});
ipcMain.handle('open-admin', async () => {
  const adminWin = new BrowserWindow({
    width: 1280, height: 820, minWidth: 900, minHeight: 600,
    backgroundColor: '#0A0106', autoHideMenuBar: true,
    icon: path.join(__dirname, '..', 'assets', 'icon.ico'),
    title: 'Replix Admin',
    webPreferences: {
      nodeIntegration: false, contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      webSecurity: true,
    },
  });
  Menu.setApplicationMenu(null);
  adminWin.webContents.session.webRequest.onBeforeSendHeaders((details, callback) => {
    details.requestHeaders['x-replix-desktop'] = '1';
    details.requestHeaders['x-replix-hwid'] = getHWID();
    callback({ requestHeaders: details.requestHeaders });
  });
  adminWin.webContents.on('did-finish-load', () => {
    adminWin.webContents.executeJavaScript(
      `window.__REPLIX_HWID__ = ${JSON.stringify(getHWID())}; window.__REPLIX_DESKTOP__ = true;`
    ).catch(() => {});
  });
  adminWin.loadURL(`${BASE_URL}/replix-admin-panel`);
});

// ---------------------------------------------------------------- app lifecycle
app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  createSplash();
  createTray();

  try {
    await waitForServer();
  } catch (err) {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    dialog.showErrorBox('Replix — Connection Error',
      IS_DEV
        ? `Could not start local server.\n\n${err.message}`
        : `Could not connect to Replix server.\n\nCheck your internet connection and try again.\n\n${err.message}`
    );
    app.quit();
    return;
  }

  const win = createMainWindow();
  win.loadURL(`${BASE_URL}/login`);
  win.once('ready-to-show', () => {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    win.show();
    win.focus();
  });

  setupAutoUpdater();
});

app.on('window-all-closed', () => {
  if (process.platform === 'darwin') { stopPythonServer(); app.quit(); }
});
app.on('activate', () => { mainWindow?.show(); });
app.on('before-quit', () => { app.isQuitting = true; stopPythonServer(); });

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { mainWindow?.show(); mainWindow?.focus(); });
}
