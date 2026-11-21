/**
 * Preload — exposes safe IPC bridges to the renderer (web app).
 * Never exposes Node.js APIs directly.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('replixDesktop', {
  // Get this machine's HWID
  getHWID: () => ipcRenderer.invoke('get-hwid'),

  // Open admin panel in separate window (only works for admins)
  openAdmin: () => ipcRenderer.invoke('open-admin'),

  // Auto-update
  checkForUpdates: () => ipcRenderer.send('check-for-updates'),
  onUpdateAvailable: (cb) => ipcRenderer.on('update-available', (_, info) => cb(info)),
  onUpdateProgress: (cb) => ipcRenderer.on('update-download-progress', (_, p) => cb(p)),
  onUpdateDownloaded: (cb) => ipcRenderer.on('update-downloaded', (_, info) => cb(info)),
  installUpdate: () => ipcRenderer.send('install-update'),

  // Open folder in system file manager
  openFolder: (p) => ipcRenderer.invoke('open-folder', p),

  // Open external link in default browser
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  // Platform info
  platform: process.platform,
  isDesktop: true,
});
