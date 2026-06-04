const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

const FLASK_PORT = 5003;
const FLASK_TIMEOUT = 30000; // 30s max wait for Flask startup
const HEALTH_CHECK_INTERVAL = 10000; // health check every 10s

let mainWindow = null;
let flaskProcess = null;

// ── Path resolution ──────────────────────────────────────────────

function isDev() {
  return !app.isPackaged;
}

function getPythonPath() {
  if (isDev()) {
    return process.platform === 'win32' ? 'python' : 'python3';
  }
  return path.join(process.resourcesPath, 'python', 'python.exe');
}

function getAppPath() {
  if (isDev()) {
    return path.resolve(__dirname, '..');
  }
  return path.join(process.resourcesPath, 'app');
}

function getIconPath() {
  return path.join(__dirname, 'icon.ico');
}

// ── Flask process management ─────────────────────────────────────

function startFlask() {
  const pythonPath = getPythonPath();
  const appPath = getAppPath();
  const appPy = path.join(appPath, 'app.py');

  flaskProcess = spawn(pythonPath, [appPy], {
    cwd: appPath,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      FLASK_ENV: isDev() ? 'development' : 'production',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  flaskProcess.stdout.on('data', (data) => {
    const text = data.toString();
    console.log('[flask]', text.trim());
  });

  flaskProcess.stderr.on('data', (data) => {
    console.log('[flask:err]', data.toString().trim());
  });

  flaskProcess.on('error', (err) => {
    console.error('[flask] failed to start:', err.message);
    showErrorDialog('启动 Flask 后端失败', err.message);
  });

  flaskProcess.on('exit', (code, signal) => {
    console.log(`[flask] exited (code=${code}, signal=${signal})`);
    if (mainWindow && !mainWindow.isDestroyed()) {
      showFlaskCrash();
    }
  });
}

function stopFlask() {
  if (flaskProcess) {
    flaskProcess.kill();
    flaskProcess = null;
  }
}

// ── Health checks ────────────────────────────────────────────────

function checkFlaskReady() {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${FLASK_PORT}/`, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(2000, () => { req.destroy(); resolve(false); });
  });
}

async function waitForFlask(timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await checkFlaskReady()) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

let healthTimer = null;
let flaskWasDown = false;

function startHealthCheck() {
  flaskWasDown = false;
  healthTimer = setInterval(async () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    const ok = await checkFlaskReady();
    if (!ok) {
      flaskWasDown = true;
      showFlaskCrash();
    } else if (flaskWasDown && mainWindow && !mainWindow.isDestroyed()) {
      // Flask recovered — reload the app
      flaskWasDown = false;
      mainWindow.loadURL(`http://127.0.0.1:${FLASK_PORT}/`);
    }
  }, HEALTH_CHECK_INTERVAL);
}

function stopHealthCheck() {
  if (healthTimer) {
    clearInterval(healthTimer);
    healthTimer = null;
  }
}

// ── Window management ────────────────────────────────────────────

function showLoading() {
  const loadingHTML = `<!DOCTYPE html>
<html><body style="display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#1e1e2e;color:#cdd6f4;font-family:sans-serif;flex-direction:column;">
  <svg width="64" height="64" viewBox="0 0 64 64">
    <circle cx="32" cy="32" r="28" fill="none" stroke="#89b4fa" stroke-width="4">
      <animate attributeName="r" values="28;24;28" dur="1.5s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="1;0.4;1" dur="1.5s" repeatCount="indefinite"/>
    </circle>
  </svg>
  <h2 style="margin-top:24px;font-weight:400;">正在启动服务...</h2>
</body></html>`;

  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(loadingHTML)}`);
  }
}

function showFlaskCrash() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const errorHTML = `<!DOCTYPE html>
<html><body style="display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#1e1e2e;color:#cdd6f4;font-family:sans-serif;flex-direction:column;">
  <div style="font-size:48px;margin-bottom:16px;">⚠️</div>
  <h2 style="font-weight:400;">后端服务意外停止</h2>
  <p style="color:#6c7086;margin-bottom:24px;">点击重启按钮重新启动应用</p>
  <button onclick="if(window.electronAPI)window.electronAPI.restartBackend()" style="padding:10px 32px;background:#89b4fa;color:#1e1e2e;border:none;border-radius:6px;font-size:14px;cursor:pointer;">重启</button>
</body></html>`;
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(errorHTML)}`);
}

function showTimeout() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const timeoutHTML = `<!DOCTYPE html>
<html><body style="display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#1e1e2e;color:#cdd6f4;font-family:sans-serif;flex-direction:column;">
  <div style="font-size:48px;margin-bottom:16px;">⏰</div>
  <h2 style="font-weight:400;">启动超时</h2>
  <p style="color:#6c7086;max-width:400px;text-align:center;">Flask 后端在 ${FLASK_TIMEOUT / 1000} 秒内未启动完成。请检查运行时环境后重试。</p>
</body></html>`;
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(timeoutHTML)}`);
}

function showErrorDialog(title, message) {
  dialog.showErrorBox(title, message);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    title: 'DA数据清洗业务AI应用',
    icon: getIconPath(),
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
    stopHealthCheck();
    stopFlask();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    require('electron').shell.openExternal(url);
    return { action: 'deny' };
  });
}

// ── IPC handlers ─────────────────────────────────────────────────

ipcMain.handle('get-app-info', () => ({
  version: app.getVersion(),
  name: app.getName(),
  arch: process.arch,
  platform: process.platform,
  flaskPort: FLASK_PORT,
}));

ipcMain.handle('restart-backend', async () => {
  stopHealthCheck();
  stopFlask();
  showLoading();
  startFlask();
  const ready = await waitForFlask(FLASK_TIMEOUT);
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (ready) {
      mainWindow.loadURL(`http://127.0.0.1:${FLASK_PORT}/`);
    } else {
      showTimeout();
    }
  }
  startHealthCheck();
  return { success: ready };
});

ipcMain.handle('show-save-dialog', async (_event, options) => {
  if (!mainWindow) return { canceled: true };
  return dialog.showSaveDialog(mainWindow, options);
});

// ── App lifecycle ────────────────────────────────────────────────

app.whenReady().then(async () => {
  createWindow();
  showLoading();

  // Check Python runtime exists (production mode only)
  if (!isDev()) {
    const pythonPath = getPythonPath();
    const fs = require('fs');
    if (!fs.existsSync(pythonPath)) {
      showErrorDialog('运行环境缺失', `未找到 Python 运行时：${pythonPath}\n请重新安装应用。`);
      app.quit();
      return;
    }
  }

  startFlask();
  const ready = await waitForFlask(FLASK_TIMEOUT);

  if (!mainWindow || mainWindow.isDestroyed()) return;

  if (ready) {
    mainWindow.loadURL(`http://127.0.0.1:${FLASK_PORT}/`);
    startHealthCheck();
  } else {
    showTimeout();
  }
});

app.on('window-all-closed', () => {
  stopHealthCheck();
  stopFlask();
  app.quit();
});

app.on('before-quit', () => {
  stopHealthCheck();
  stopFlask();
});
