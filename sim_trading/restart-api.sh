#!/bin/bash
# 重启交易系统API
cd /root/.openclaw/workspace/sim_trading
pkill -f "gunicorn.*app" 2>/dev/null
sleep 1
exec gunicorn -w 2 -b 0.0.0.0:80 app:app --timeout 300 \
  --access-logfile /var/log/gunicorn_access.log \
  --error-logfile /var/log/gunicorn_error.log \
  --daemon
