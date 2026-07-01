"""
配置集中管理
"""
import os

# 加载 .env 环境变量
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
try:
    if os.path.exists(_env_path):
        with open(_env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k, v)
except Exception:
    pass


# Feature Flags
from openclaw.feature_flags import is_feature_enabled

MARKET_CACHE_ENABLED = is_feature_enabled("MARKET_CACHE")
STATS_CACHE_ENABLED = is_feature_enabled("STATS_CACHE")
STOCK_MONITOR_ENABLED = is_feature_enabled("STOCK_MONITOR")

# 缓存 TTL（秒）
CACHE_TTL = 30

# A股市场规则常量
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 30
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MIN = 0
AM_CLOSE_HOUR = 11
AM_CLOSE_MIN = 30
PM_OPEN_HOUR = 13

# 初始资金
INITIAL_CAPITAL = 100000.0

# Star Office UI 后端地址
STAR_OFFICE_BACKEND = 'http://127.0.0.1:19000'

# Agent 状态文件
STAR_OFFICE_STATE_FILE = os.environ.get(
    "STAR_OFFICE_STATE_FILE",
    "/root/Star-Office-UI/state.json"
)
