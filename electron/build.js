/**
 * DA数据清洗业务AI应用 - 自动化打包脚本
 *
 * 运行方式: node build.js
 *
 * 功能:
 *   1. 复制 Flask 应用代码到 app_dist/
 *   2. 下载便携版 Python 运行时（仅 Windows 构建需要）
 *   3. 可选: 安装 pip 依赖
 *
 * 注意: 完整构建生成 NSIS 安装程序(.exe)需要 Windows 环境。
 *       当前 macOS/Linux 仅完成文件准备，然后运行:
 *         npx electron-builder --win
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const https = require('https');

// ── Config ──────────────────────────────────────────────────────

const ROOT = path.resolve(__dirname, '..');           // 项目根目录
const APP_DIST = path.resolve(__dirname, '..', 'app_dist');   // Flask 代码副本
const RUNTIME = path.resolve(__dirname, '..', 'runtime');      // 便携 Python
const DIST_ELECTRON = path.resolve(__dirname, '..', 'dist-electron'); // electron-builder 输出

const PYTHON_VERSION = '3.12.7';
const PYTHON_BUILD_TAG = '20241002';
const PYTHON_URL = `https://github.com/indygreg/python-build-standalone/releases/download/${PYTHON_BUILD_TAG}/cpython-${PYTHON_VERSION}+${PYTHON_BUILD_TAG}-x86_64-pc-windows-msvc-install_only.tar.gz`;
const PYTHON_CHECKSUM = null; // optional

// Files/dirs to copy from project root to app_dist/
const APP_SOURCES = [
  'app.py',
  'config.py',
  'requirements.txt',
  '.env.example',
  { src: 'modules', dest: 'modules' },
  { src: 'templates', dest: 'templates' },
  { src: 'static', dest: 'static' },
];

// ── Helpers ─────────────────────────────────────────────────────

function log(label, msg) {
  const ts = new Date().toISOString().slice(11, 19);
  console.log(`[${ts}] [${label}] ${msg}`);
}

function info(msg) { log('INFO', msg); }
function ok(msg)   { log(' OK ', msg); }
function warn(msg) { log('WARN', msg); }
function err(msg)  { log('ERR ', msg); }

function rmrf(dir) {
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
    info(`已删除: ${path.basename(dir)}/`);
  }
}

function mkdir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function copy(src, dest) {
  if (!fs.existsSync(src)) {
    warn(`源文件不存在，跳过: ${src}`);
    return false;
  }
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.cpSync(src, dest, { recursive: true });
    info(`复制目录: ${path.relative(ROOT, src)} → ${path.relative(ROOT, dest)}`);
  } else {
    mkdir(path.dirname(dest));
    fs.copyFileSync(src, dest);
    info(`复制文件: ${path.basename(src)} → ${path.relative(ROOT, dest)}`);
  }
  return true;
}

function exec(cmd, opts = {}) {
  info(`执行: ${cmd}`);
  try {
    execSync(cmd, { stdio: 'inherit', ...opts });
  } catch (e) {
    err(`命令失败 (exit=${e.status}): ${cmd}`);
    if (!opts.ignoreError) process.exit(1);
  }
}

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    if (fs.existsSync(dest)) {
      info(`文件已存在，跳过下载: ${path.basename(dest)}`);
      resolve();
      return;
    }
    const file = fs.createWriteStream(dest);
    info(`下载中: ${url}`);
    https.get(url, (res) => {
      if (res.statusCode === 302 || res.statusCode === 301) {
        file.close();
        fs.unlinkSync(dest);
        return downloadFile(res.headers.location, dest).then(resolve, reject);
      }
      if (res.statusCode !== 200) {
        file.close();
        fs.unlinkSync(dest);
        reject(new Error(`下载失败 HTTP ${res.statusCode}`));
        return;
      }
      const total = parseInt(res.headers['content-length'], 10);
      let downloaded = 0;
      res.on('data', (chunk) => {
        downloaded += chunk.length;
        if (total && process.stdout.isTTY) {
          const pct = (downloaded / total * 100).toFixed(1);
          process.stdout.write(`\r  进度: ${pct}% (${(downloaded/1024/1024).toFixed(1)}MB / ${(total/1024/1024).toFixed(1)}MB)`);
        }
      });
      res.pipe(file);
      file.on('finish', () => {
        file.close();
        if (process.stdout.isTTY) process.stdout.write('\n');
        ok(`下载完成: ${path.basename(dest)}`);
        resolve();
      });
    }).on('error', (e) => {
      file.close();
      if (fs.existsSync(dest)) fs.unlinkSync(dest);
      reject(e);
    });
  });
}

function isWindows() {
  return process.platform === 'win32';
}

// ── Steps ───────────────────────────────────────────────────────

function stepCopyApp() {
  info('========== 步骤 1/3: 复制 Flask 应用代码 ==========');
  rmrf(APP_DIST);
  mkdir(APP_DIST);

  for (const item of APP_SOURCES) {
    if (typeof item === 'string') {
      const src = path.join(ROOT, item);
      const dest = path.join(APP_DIST, item);
      if (!copy(src, dest) && item === '.env.example') {
        // optional
      }
    } else {
      const src = path.join(ROOT, item.src);
      const dest = path.join(APP_DIST, item.dest);
      copy(src, dest);
    }
  }

  // Also copy preset_rules.json if it exists
  const rulesSrc = path.join(ROOT, 'temp', 'preset_rules.json');
  if (fs.existsSync(rulesSrc)) {
    copy(rulesSrc, path.join(APP_DIST, 'temp', 'preset_rules.json'));
  }

  ok(`应用代码已复制到: ${APP_DIST}`);
}

async function stepDownloadPython() {
  info('========== 步骤 2/3: 下载便携版 Python ==========');

  const pythonDir = path.join(RUNTIME, 'python');
  if (fs.existsSync(pythonDir) && fs.readdirSync(pythonDir).length > 0) {
    info('Python 运行时已存在，跳过下载。如需重新下载，请先删除 runtime/ 目录。');
    return;
  }

  mkdir(RUNTIME);
  const tarball = path.join(RUNTIME, `python-${PYTHON_VERSION}-windows-x86_64.tar.gz`);

  try {
    await downloadFile(PYTHON_URL, tarball);
  } catch (e) {
    err(`Python 下载失败: ${e.message}`);
    warn('请手动下载并解压至 runtime/python/ 目录');
    warn(`下载地址: ${PYTHON_URL}`);
    return;
  }

  info('解压中...');
  mkdir(pythonDir);
  exec(`tar -xzf "${tarball}" -C "${pythonDir}" --strip-components 1`, {
    cwd: RUNTIME,
  });
  fs.unlinkSync(tarball);

  // Verify Python executable exists
  const pythonExe = path.join(pythonDir, 'python.exe');
  if (fs.existsSync(pythonExe)) {
    ok(`Python 运行时就绪: ${pythonDir}`);
  } else {
    warn('Python 解压后未找到 python.exe，请检查下载内容');
  }
}

function stepInstallDeps() {
  info('========== 步骤 3/3: 安装 Python 依赖 ==========');

  const pythonDir = path.join(RUNTIME, 'python');
  const requirements = path.join(APP_DIST, 'requirements.txt');

  if (!fs.existsSync(pythonDir)) {
    warn('Python 运行时不存在，跳过依赖安装');
    warn('请在 Windows 环境中运行: runtime\\python\\python.exe -m pip install -r requirements.txt');
    return;
  }

  if (!fs.existsSync(requirements)) {
    warn('requirements.txt 不存在，跳过依赖安装');
    return;
  }

  if (!isWindows()) {
    warn('非 Windows 环境，跳过 pip 安装（无法跨架构安装 Windows wheel）');
    warn('请在 Windows 环境中运行以下命令:');
    warn(`  runtime\\python\\python.exe -m pip install -r app_dist\\requirements.txt`);
    return;
  }

  exec(`"${path.join(pythonDir, 'python.exe')}" -m pip install -r "${requirements}"`, {
    cwd: RUNTIME,
  });
  ok('Python 依赖安装完成');
}

function printSummary() {
  const lines = [
    '',
    '═══════════════════════════════════════════',
    '  构建准备完成',
    '═══════════════════════════════════════════',
    '',
    '  📁 app_dist/    — Flask 应用代码',
    `     ${APP_DIST}`,
  ];

  const pythonDir = path.join(RUNTIME, 'python');
  if (fs.existsSync(pythonDir)) {
    lines.push(
      `  📁 runtime/     — Python 运行时`,
      `     ${RUNTIME}`,
    );
  }

  lines.push(
    '',
    '  🚀 完整构建 NSIS 安装程序:',
    '     在 Windows 环境中运行:',
    '     1. cd electron',
    '     2. node build.js           # 准备文件 + 安装依赖',
    '     3. npx electron-builder     # 生成 NSIS 安装程序',
    '',
    '     或在 macOS/Linux 进行跨平台构建:',
    '     (需要 Wine 支持 NSIS)',
    '     cd electron && npx electron-builder --win',
    '',
    '  🖥️  开发模式测试:',
    '     cd electron && npm start',
    '',
  );

  console.log(lines.join('\n'));
}

// ── Main ────────────────────────────────────────────────────────

async function main() {
  console.log('');
  info(`DA数据清洗业务AI应用 打包工具`);
  info(`应用版本: 1.0.0`);
  info(`平台: ${process.platform} (${process.arch})`);
  info(`Python 版本: ${PYTHON_VERSION}`);
  console.log('');

  stepCopyApp();
  await stepDownloadPython();
  stepInstallDeps();
  printSummary();
}

main().catch((e) => {
  err(`构建失败: ${e.message}`);
  process.exit(1);
});
