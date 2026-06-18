#!/bin/bash
# 自动备份trading.db，保留最近30个备份
BACKUP_DIR="/root/.openclaw/workspace/sim_trading/backups"
DB="/root/.openclaw/workspace/sim_trading/data/trading.db"
mkdir -p $BACKUP_DIR
cp "$DB" "$BACKUP_DIR/trading_$(date +%Y%m%d_%H%M).db"
# 清理30天前的备份
find $BACKUP_DIR -name "trading_*.db" -mtime +30 -delete 2>/dev/null
