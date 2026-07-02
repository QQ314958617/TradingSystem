"""
蛋蛋模拟交易系统 - Flask 入口
"""
import os
import sys
import logging

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载配置（含 .env 和 feature flags）
import config  # noqa: F401

from flask import Flask
import database as db
from routes import register_blueprints


# 多策略框架 - 注册策略模块
from trading.strategies import StrategyManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)

# 创建 Flask 应用
app = Flask(__name__, static_folder=None)
app.config['JSON_AS_ASCII'] = False

# 注册所有 Blueprint 路由
register_blueprints(app)

# 策略管理器
strategy_mgr = StrategyManager()



@app.before_request
def before_first_request():
    """首次请求前初始化数据库"""
    if not hasattr(app, '_db_initialized'):
        db.init_database()
        app._db_initialized = True


if __name__ == '__main__':
    db.init_database()
    app.run(host='0.0.0.0', port=80, debug=False, threaded=True)
