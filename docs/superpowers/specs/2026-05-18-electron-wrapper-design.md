# DA数据清洗业务AI应用 Electron 封装设计

> **目标：** 为现有 Flask Web 应用套上 Electron 桌面壳，生成 Windows 单文件安装程序（.exe），用户双击即可使用，无需安装 Python 或任何依赖。

**For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this spec task-by-task.

---

## 一、架构概览

```
┌─────────────────────────────────────────┐
│            Electron 主进程               │
│  main.js                                │
│  ├─ 启动 Flask (child_process.spawn)    │
│  ├─ 创建 BrowserWindow                  │
│  └─ 管理进程生命周期                     │
├─────────────────────────────────────────┤
│            BrowserWindow                 │
│  加载 http://localhost:5003             │
│  标准标题栏 + 关闭/最小化/最大化         │
├─────────────────────────────────────────┤
│            Flask 子进程                  │
│  runtime/python/python.exe app.py       │
│  监听 127.0.0.1:5003                    │
└─────────────────────────────────────────┘
```

## 二、工作目录结构

```
DA数据清洗业务AI应用/          ← 安装目录
├── app.exe                   ← Electron 可执行文件（electron-builder 生成）
├── runtime/
│   └── python/               ← 便携版 Python（python-build-standalone）
│       └── python.exe
│       └── Lib/
│       └── Scripts/
│       └── ...
├── resources/
│   ├── app/                  ← 应用代码
│   │   ├── app.py
│   │   ├── config.py
│   │   ├── requirements.txt
│   │   ├── modules/
│   │   ├── templates/
│   │   └── static/
│   └── icon.ico
├── temp/                     ← 运行时数据（用户数据目录）
│   ├── db/
│   ├── uploads/
│   └── preset_rules.json
└── uninstall.exe             ← electron-builder 自动生成
```

## 三、开发期项目结构

```
财智灵契/
├── app.py                   # Flask 后端（不变）
├── modules/                 # Python 模块（不变）
├── templates/               # 前端模板（不变）
├── static/                  # 静态资源（不变）
├── electron/
│   ├── main.js              # Electron 主进程
│   ├── preload.js           # 预加载脚本
│   ├── package.json         # Electron 依赖声明
│   ├── icon.ico             # 应用图标（EY logo）
│   ├── build.js             # 自动化打包脚本
│   └── README.md
└── requirements.txt         # （不变）
```

## 四、主进程设计（main.js）

### 4.1 Flask 子进程管理

```javascript
// 伪代码逻辑
const pythonPath = path.join(process.resourcesPath, 'python', 'python.exe');
const appPath = path.join(process.resourcesPath, 'app');

let flaskProcess = spawn(pythonPath, ['app.py'], {
  cwd: appPath,
  env: {
    ...process.env,
    PYTHONUNBUFFERED: '1',
  }
});

// 监听端口就绪
flaskProcess.stdout.on('data', data => {
  if (data.toString().includes('Running on')) {
    loadBrowserWindow();
  }
});

// 窗口关闭时杀掉 Flask
app.on('window-all-closed', () => {
  flaskProcess.kill();
  app.quit();
});
```

### 4.2 BrowserWindow

```javascript
const win = new BrowserWindow({
  width: 1400,
  height: 900,
  title: 'DA数据清洗业务AI应用',
  icon: path.join(__dirname, 'icon.ico'),
  webPreferences: {
    preload: path.join(__dirname, 'preload.js'),
  },
  autoHideMenuBar: true,
});

win.loadURL('http://localhost:5003');

// 启动时显示加载页，Flask 就绪后切换
win.on('did-fail-load', () => {
  win.loadFile('loading.html'); // 后续重试
});
```

### 4.3 启动流程

```
用户双击 app.exe
  → Electron 初始化
  → 检测 runtime/python/python.exe 是否存在
  → 如果缺失 → 弹框报错（安装损坏）
  → spawn Flask 子进程
  → 打开 BrowserWindow（先显示 loading.html）
  → 轮询 http://localhost:5003（每500ms，最多30秒）
  → 就绪 → 加载应用
  → 每隔 10 秒探活 Flask 进程，挂了则显示错误页
```

## 五、可移植 Python 运行时

用 [python-build-standalone](https://github.com/indygreg/python-build-standalone) 提供的 Windows x86_64 便携版：

| 步骤 | 说明 |
|------|------|
| 下载 | `python-build-standalone` 的 `cpython-3.12.*-x86_64-pc-windows-msvc-install_only.tar.gz` |
| 解压 | 到 `electron/runtime/python/` |
| 安装依赖 | `pip install -r requirements.txt --target runtime/python/Lib/site-packages`（预先完成） |
| 打包 | electron-builder 将 `runtime/` 打进安装包 |

## 六、打包脚本（build.js）

```javascript
// 伪代码流程
async function build() {
  // 1. 下载 portable Python（若不存在缓存）
  // 2. 解压到 runtime/python/
  // 3. pip install -r requirements.txt
  // 4. 复制 app.py, modules/, templates/, static/ 到 resources/app/
  // 5. 复制 preset_rules.json
  // 6. electron-builder 打包为 NSIS 安装程序
}
```

## 七、安装包规格

| 项目 | 值 |
|------|-----|
| 安装程序格式 | NSIS（单文件 .exe） |
| 安装后大小 | ~120-150MB |
| 安装选项 | 桌面快捷方式、开始菜单、添加/移除程序 |
| 最低系统 | Windows 10 x64 |
| Python 版本 | 3.12.x（便携版） |

## 八、局限性

1. **macOS/Linux 不支持** — 如需额外适配，需要为各平台单独构建
2. **包体大**（~150MB）— 主要来自 Electron + Python 运行时
3. **首启较慢** — 需要 2-5 秒等待 Flask 启动
4. **不涉及修改 Flask 后端** — 所有逻辑保持原样

## 九、安装文件清单

安装程序包含：

- `app.exe` — Electron 壳
- `runtime/python/` — 便携 Python（~80MB）
- `resources/app/` — Flask 应用代码 + 依赖（~30MB）
- `resources/icon.ico` — 应用图标
- `temp/preset_rules.json` — 初始规则文件
- NSIS uninstaller（自动生成）
