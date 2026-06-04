# DA数据清洗业务AI应用 - Electron 桌面壳

## 快速开始

```bash
# 安装依赖
cd electron
npm install

# 开发模式 (macOS: 直接启动 Flask + 浏览器)
bash mac-dev.sh

# Electron 开发模式 (macOS 可能不可用，详见下方说明)
npm start
```

## 目录结构

```
electron/
├── main.js         # Electron 主进程
├── preload.js      # 预加载脚本 (contextBridge)
├── package.json    # 依赖 + electron-builder 配置
├── build.js        # 自动化打包脚本
├── icon.ico        # 应用图标 (EY logo)
├── mac-dev.sh      # macOS 开发启动脚本
└── README.md
```

## 项目结构

```
财智灵契/
├── electron/       # ← Electron 封装 (你在这里)
├── app.py          # Flask 后端
├── modules/        # Python 模块
├── templates/      # 前端模板
├── static/         # 静态资源
├── app_dist/       # (构建产物) 打包后的 Flask 代码
├── runtime/        # (构建产物) 便携 Python 运行时
├── dist-electron/  # (构建产物) NSIS 安装程序
└── requirements.txt
```

## 构建 Windows 安装程序

完整构建需要在 **Windows 环境** 中运行:

```bash
cd electron
npm run build-dev    # 准备文件
npx electron-builder # 生成 NSIS 安装程序
```

输出: `dist-electron/DA数据清洗业务AI应用 Setup *.exe`

## macOS 开发说明

**已知问题:** Electron v33+ 在 macOS Sequoia 26.4 (arm64) 上存在 `require('electron')`
内置模块截获不工作的问题。这是因为该 macOS 版本过于新，Electron 尚未完善适配。

- `npm start` (electron .) 在当前 macOS 版本上**不可用**
- 使用 `bash mac-dev.sh` 直接启动 Flask + 浏览器进行开发
- Windows 构建不受影响

## 构建流程

1. `node build.js` — 复制 Flask 代码到 `app_dist/`，可选下载便携 Python
2. `npx electron-builder` — 打包为 NSIS 安装程序
3. 输出在 `dist-electron/` 目录

## 技术栈

- **Electron 35** — 桌面壳
- **electron-builder** — 打包工具 (NSIS)
- **python-build-standalone** — 便携 Python 运行时
- **Flask** — Web 后端 (子进程)
