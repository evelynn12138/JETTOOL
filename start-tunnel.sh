#!/bin/bash
# Cloudflare Tunnel 启动脚本（HTTP/2 模式绕过公司防火墙）
# 快速隧道每次启动 URL 会变，查看当前 URL 请运行：cat /tmp/cloudflared-url.txt

LOGFILE="/tmp/cloudflared-tunnel.log"
URLFILE="/tmp/cloudflared-url.txt"

# 启动 tunnel
/opt/homebrew/bin/cloudflared tunnel --url http://localhost:5003 --protocol http2 > "$LOGFILE" 2>&1 &

# 等待并提取 URL
sleep 8
URL=$(grep -o 'https://[a-z-]*\.trycloudflare\.com' "$LOGFILE" | head -1)
if [ -n "$URL" ]; then
    echo "$URL" > "$URLFILE"
    echo "Tunnel URL: $URL"
else
    echo "Waiting for tunnel URL..." > "$URLFILE"
fi
