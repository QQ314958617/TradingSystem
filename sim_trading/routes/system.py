"""
系统路由: /api/dashboard, /api/agent_status, /api/cost, /api/watchlist, /api/alerts
"""
import json
import os
import logging
from datetime import datetime, date, timedelta, timezone
from flask import Blueprint, jsonify, request, render_template, make_response, send_from_directory

import akshare as ak
import requests
import database as db
from services.quote import get_tencent_quote
from services.cache import cache
from config import STAR_OFFICE_STATE_FILE

logger = logging.getLogger(__name__)

system_bp = Blueprint('system', __name__)


# 文件下载目录配置
_DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'downloads')
os.makedirs(_DOWNLOAD_DIR, exist_ok=True)


@system_bp.route('/download/<filename>')
def download_file(filename):
    """下载文件"""
    # 安全校验，防止路径穿越
    safe_path = os.path.normpath(filename)
    if '..' in safe_path or safe_path.startswith('/'):
        return jsonify({'error': 'invalid filename'}), 400
    return send_from_directory(_DOWNLOAD_DIR, safe_path, as_attachment=True)


@system_bp.route('/')
def index():
    response = make_response(render_template('dashboard.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@system_bp.route('/api/dashboard')
def get_dashboard():
    """一次请求拿全部面板数据"""
    # 自动补全缺失的每日净值记录
    try:
        from zoneinfo import ZoneInfo
        bj = ZoneInfo("Asia/Shanghai")
        today = datetime.now(bj).date()
        existing = db.get_equity_curve(days=365)
        existing_dates = {r['date'] for r in existing}
        account = db.get_account()
        total_val = account.get('total_value', 50000)
        cash_val = account.get('cash', 50000)
        pos_val = total_val - cash_val

        if existing:
            start = date.fromisoformat(existing[0]['date'])
        else:
            start = today - timedelta(days=30)
        d = start
        while d <= today:
            ds = d.isoformat()
            if ds not in existing_dates:
                db.add_equity_record(ds, total_val, cash_val, pos_val)
            d += timedelta(days=1)
    except Exception as e:
        logger.warning(f"净值补全失败: {e}")

    account = db.get_account()
    positions = db.get_positions()
    trades = db.get_trades(limit=50)
    reviews = db.get_reviews(limit=20)
    stats = db.get_trade_stats()
    equity = db.get_equity_curve(days=60)

    # 大盘指数
    index_data = {}
    try:
        import pandas as pd
        url = "https://qt.gtimg.cn/q=sh000001"
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
        r = requests.get(url, headers=headers, timeout=5)
        fields = r.text.split('="')[1].strip('"').split('~')
        current_price = float(fields[3]) if fields[3] != '-' else 0
        try:
            df = ak.stock_zh_index_daily(symbol='sh000001')
            df = df.tail(15).copy()
            df['ma5'] = df['close'].rolling(window=5).mean()
            df['ma10'] = df['close'].rolling(window=10).mean()
            latest = df.iloc[-1]
            ma5 = round(latest['ma5'], 2) if pd.notna(latest['ma5']) else 0
            ma10 = round(latest['ma10'], 2) if pd.notna(latest['ma10']) else 0
        except Exception:
            ma5 = current_price
            ma10 = current_price
        index_data = {
            'name': '上证指数', 'code': '000001',
            'price': current_price,
            'change_pct': float(fields[32]) if len(fields) > 32 and fields[32] != '-' else 0,
            'ma5': ma5, 'ma10': ma10,
            'above_ma5': bool(current_price > ma5) if ma5 > 0 else False,
            'above_ma10': bool(current_price > ma10) if ma10 > 0 else False,
        }
    except Exception as e:
        logger.warning(f"获取大盘指数失败: {e}")
        index_data = {'name': '上证指数', 'code': '000001', 'price': 0, 'change_pct': 0, 'ma5': 0, 'ma10': 0}

    # 持仓详情（带实时价格）
    pos_detail = {}
    codes = [p['stock_code'] for p in positions]
    quotes = {}
    if codes:
        try:
            quotes = get_tencent_quote(codes)
        except Exception as e:
            logger.warning(f"获取持仓行情失败: {e}")
    for pos in positions:
        code = pos['stock_code']
        q = quotes.get(code, {})
        cp = q.get('price', pos['avg_cost'])
        pos_detail[code] = {
            'stock_name': pos.get('stock_name') or q.get('name', ''),
            'shares': pos['shares'], 'avg_cost': pos['avg_cost'],
            'current_price': cp, 'change_pct': q.get('change_pct', 0),
            'market_value': cp * pos['shares'],
            'profit': (cp - pos['avg_cost']) * pos['shares'],
            'profit_pct': ((cp - pos['avg_cost']) / pos['avg_cost'] * 100) if pos['avg_cost'] else 0,
            'strategy_id': pos.get('strategy_id'),
        }

    # 多策略信息
    strategies = db.get_strategies()
    strategy_stats = {}
    for s in strategies:
        sid = s['id']
        s_stats = db.get_trade_stats(strategy_id=sid)
        s_positions = db.get_positions(strategy_id=sid)
        strategy_stats[str(sid)] = {
            'name': s['name'],
            'type': s['type'],
            'capital': s['capital'],
            'is_active': s['is_active'],
            'stats': s_stats,
            'position_count': len(s_positions),
        }

    return jsonify({
        'account': account, 'positions': pos_detail,
        'trades': trades, 'reviews': reviews,
        'stats': stats, 'equity': equity, 'index': index_data,
        'strategies': strategy_stats,
    })


# ========== Agent 状态 ==========

@system_bp.route('/api/agent_status', methods=['GET', 'POST'])
def agent_status_route():
    """获取或设置 Agent 状态"""
    from openclaw.state_manager import set_agent_status, VALID_AGENT_STATES

    if request.method == 'GET':
        try:
            if os.path.exists(STAR_OFFICE_STATE_FILE):
                with open(STAR_OFFICE_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return jsonify({
                    "state": data.get("state", "idle"),
                    "detail": data.get("detail", "")
                })
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"读取状态文件失败: {e}")
        return jsonify({"state": "idle", "detail": ""})

    # POST
    try:
        data = request.json or {}
        state = data.get('state', 'idle')
        detail = data.get('detail', '')

        if state not in VALID_AGENT_STATES:
            return jsonify({'error': f'Invalid state. Valid: {list(VALID_AGENT_STATES)}'}), 400

        set_agent_status(state, detail)
        return jsonify({'state': state, 'detail': detail})
    except Exception as e:
        logger.error(f"设置Agent状态失败: {e}")
        return jsonify({'error': str(e)}), 500


# ========== 成本追踪 ==========

@system_bp.route('/api/cost', methods=['GET'])
def cost_route():
    """获取成本报表"""
    fmt = request.args.get('format', 'summary')

    from openclaw.cost_tracker import (
        get_cost_state, get_cost_summary,
        get_recent_calls, get_model_usage
    )

    state = get_cost_state()

    if fmt == 'detail':
        return jsonify(state.to_dict())
    elif fmt == 'recent':
        return jsonify({"calls": get_recent_calls(20)})
    elif fmt == 'model':
        return jsonify(get_model_usage())
    else:
        return jsonify({
            "summary": get_cost_summary(),
            "total_cost_usd": round(state.total_cost_usd, 6),
            "total_api_calls": state.total_api_calls,
            "total_duration_ms": state.total_duration_ms,
            "input_tokens": state.total_input_tokens,
            "output_tokens": state.total_output_tokens,
            "cache_read_tokens": state.total_cache_read_tokens,
            "cache_write_tokens": state.total_cache_write_tokens,
            "model_usage": get_model_usage(),
        })


@system_bp.route('/api/cost/reset', methods=['POST'])
def cost_reset_route():
    """重置成本计数器"""
    from openclaw.cost_tracker import reset_cost_state, save_cost_state
    reset_cost_state()
    save_cost_state()
    return jsonify({"ok": True, "message": "成本计数器已重置"})


# ========== 自选股/预警系统 ==========

@system_bp.route('/api/watchlist', methods=['GET'])
def get_watchlist():
    """获取自选股列表"""
    try:
        from openclaw.alert_system import get_watchlist as _get_watchlist
        watchlist = _get_watchlist()
        return jsonify({"watchlist": watchlist, "count": len(watchlist)})
    except Exception as e:
        logger.warning(f"获取自选股失败: {e}")
        return jsonify({"error": str(e)}), 500


@system_bp.route('/api/watchlist/add', methods=['POST'])
def add_watchlist():
    """添加自选股"""
    try:
        from openclaw.alert_system import add_to_watchlist as _add_watchlist

        data = request.json or {}
        code = data.get("code", "").strip()
        name = data.get("name", code)
        threshold = float(data.get("threshold", 5.0))

        if not code:
            return jsonify({"error": "股票代码不能为空"}), 400

        result = _add_watchlist(code, name, threshold=threshold)
        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        logger.warning(f"添加自选股失败: {e}")
        return jsonify({"error": str(e)}), 500


@system_bp.route('/api/watchlist/remove', methods=['POST'])
def remove_watchlist():
    """删除自选股"""
    try:
        from openclaw.alert_system import remove_from_watchlist as _remove_watchlist

        data = request.json or {}
        code = data.get("code", "").strip()

        if not code:
            return jsonify({"error": "股票代码不能为空"}), 400

        result = _remove_watchlist(code)
        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        logger.warning(f"删除自选股失败: {e}")
        return jsonify({"error": str(e)}), 500


@system_bp.route('/api/alerts', methods=['GET'])
def get_alerts():
    """获取预警记录"""
    try:
        from openclaw.alert_system import load_alerts, clear_old_alerts

        cleared = clear_old_alerts()
        alerts = load_alerts()
        unacknowledged = [a for a in alerts if not a.get("acknowledged", False)]

        return jsonify({
            "alerts": unacknowledged[-10:],
            "total": len(unacknowledged),
            "cleared": cleared,
        })
    except Exception as e:
        logger.warning(f"获取预警失败: {e}")
        return jsonify({"error": str(e)}), 500


@system_bp.route('/api/alerts/acknowledge', methods=['POST'])
def acknowledge_alert():
    """确认预警"""
    try:
        from openclaw.alert_system import acknowledge_alert as _acknowledge

        data = request.json or {}
        code = data.get("code", "")
        triggered_at = data.get("triggered_at", "")

        if not code or not triggered_at:
            return jsonify({"error": "参数不完整"}), 400

        _acknowledge(code, triggered_at)
        return jsonify({"success": True})
    except Exception as e:
        logger.warning(f"确认预警失败: {e}")
        return jsonify({"error": str(e)}), 500


@system_bp.route('/api/alerts/check', methods=['GET'])
def check_alerts():
    """检查预警（供定时任务调用）"""
    try:
        from openclaw.alert_system import check_and_notify
        result = check_and_notify()
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.warning(f"检查预警失败: {e}")
        return jsonify({"error": str(e)}), 500


# ========== 初始化（安全版本） ==========

@system_bp.route('/api/init', methods=['POST'])
def reset_account():
    """重置账户（需要确认参数）"""
    data = request.json or {}
    confirm = data.get('confirm', '')
    if confirm != 'RESET_ALL_DATA':
        return jsonify({
            "error": "危险操作！请传入 confirm='RESET_ALL_DATA' 确认重置",
            "hint": "POST /api/init {\"confirm\": \"RESET_ALL_DATA\"}"
        }), 400

    db_path = db.get_db_path()
    if os.path.exists(db_path):
        os.remove(db_path)
    db.init_database()
    return jsonify({"success": True, "message": "数据库已重置"})
