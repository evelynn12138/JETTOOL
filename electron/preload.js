const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // App info
  getAppInfo: () => ipcRenderer.invoke('get-app-info'),

  // Restart backend
  restartBackend: () => ipcRenderer.invoke('restart-backend'),

  // File dialog for exports
  showSaveDialog: (options) => ipcRenderer.invoke('show-save-dialog', options),

  // Listen for backend status
  onBackendStatus: (callback) => {
    ipcRenderer.on('backend-status', (_event, status) => callback(status));
  },
});
