#!/usr/bin/env python3
"""DA数据清洗业务AI应用 — PyInstaller 入口"""

import os
import sys
import webbrowser
import threading
import time

# ── PyInstaller bundle 路径修正 ──
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    BASE_DIR = sys._MEIPASS
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    # 将数据目录（session、上传、duckdb）放到用户目录下，跨会话持久化
    import config as _cfg
    data_root = os.path.join(os.path.expanduser('~'), '.da-cleaner')
    _cfg.Config.UPLOAD_FOLDER = os.path.join(data_root, 'temp')
    _cfg.Config.DUCKDB_DIR = os.path.join(data_root, 'temp', 'db')
    _cfg.Config.SESSION_FILE_DIR = os.path.join(data_root, 'session')
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _open_browser():
    """Flask 启动后自动打开浏览器"""
    time.sleep(2)
    webbrowser.open('http://127.0.0.1:5003')


if __name__ == '__main__':
    print('正在启动 DA数据清洗业务AI应用 ...')
    threading.Thread(target=_open_browser, daemon=True).start()
    from app import app
    # 确保 Flask-Session 目录存在
    sess_dir = app.config.get('SESSION_FILE_DIR', os.path.join(BASE_DIR, 'flask_session'))
    os.makedirs(sess_dir, exist_ok=True)
    app.run(host='127.0.0.1', port=5003, debug=False, use_reloader=False)
