"""
引擎路由: /api/engine/status, /api/engine/run, /api/market/scan
"""
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request

import requests
import akshare as ak
import database as db
from services.quote import get_tencent_quote, get_market_top_cached
from services.cache import cache

logger = logging.getLogger(__name__)

engine_bp = Blueprint('engine', __name__)


def _get_index_data_cached():
    """获取大盘数据"""
    try:
        import pandas as pd
        url = "https://qt.gtimg.cn/q=sh000001"
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
        r = requests.get(url, headers=headers, timeout=5)
        fields = r.text.split('="')[1].strip('"').split('~')
        current_price = float(fields[3]) if fields[3] != '-' else 0
        change_pct = float(fields[32]) if len(fields) > 32 and fields[32] != '-' else 0

        # 尝试从缓存获取均线
        cached = cache.get('index_data')
        if cached:
            return {
                "code": cached.get("code", "000001"),
                "name": cached.get("name", "上证指数"),
                "price": current_price,
                "ma5": cached.get("ma5", 0),
                "ma10": cached.get("ma10", 0),
                "change_pct": change_pct,
            }

        # 重新计算均线
        try:
            df = ak.stock_zh_index_daily(symbol='sh000001')
            df = df.tail(15).copy()
            df['ma5'] = df['close'].rolling(window=5).mean()
            df['ma10'] = df['close'].rolling(window=10).mean()
            latest = df.iloc[-1]
            ma5 = round(latest['ma5'], 2) if pd.notna(latest['ma5']) else 0
            ma10 = round(latest['ma10'], 2) if pd.notna(latest['ma10']) else 0
        except Exception:
            ma5 = 0
            ma10 = 0

        return {
            "code": "000001",
            "name": "上证指数",
            "price": current_price,
            "ma5": ma5,
            "ma10": ma10,
            "change_pct": change_pct,
        }
    except Exception as e:
        logger.warning(f"获取大盘数据失败: {e}")
        return None


def _get_portfolio_cached():
    """获取账户数据"""
    try:
        account = db.get_account()
        positions = db.get_positions()
        return {
            **account,
            'positions': {p['stock_code']: p for p in positions}
        }
    except Exception as e:
        logger.warning(f"获取账户数据失败: {e}")
        return None


@engine_bp.route('/api/engine/status', methods=['GET'])
def engine_status():
    """获取交易引擎状态"""
    index_data = _get_index_data_cached()
    portfolio = _get_portfolio_cached()

    # 获取持仓实时行情
    positions_quote = {}
    if portfolio and portfolio.get("positions"):
        codes = list(portfolio["positions"].keys())
        if codes:
            code_str = ','.join(['sh'+c if c.startswith(('6', '5')) else 'sz'+c for c in codes])
            url = f"https://qt.gtimg.cn/q={code_str}"
            try:
                r = requests.get(url, timeout=3)
                for line in r.text.strip().split('\n'):
                    if '=' in line:
                        parts = line.split('="')
                        if len(parts) < 2:
                            continue
                        fields = parts[1].strip('"').split('~')
                        if len(fields) > 10:
                            code = fields[0]
                            for prefix in ['v_szh', 'v_shsh', 'sz', 'sh']:
                                code = code.replace(prefix, '')
                            positions_quote[code] = {
                                "price": float(fields[3]) if fields[3] != '-' else 0,
                                "change_pct": float(fields[32]) if len(fields) > 32 and fields[32] != '-' else 0,
                            }
            except Exception as e:
                logger.warning(f"获取持仓行情失败: {e}")

    # 合并持仓数据
    positions = []
    if portfolio and portfolio.get("positions"):
        for code, pos in portfolio["positions"].items():
            quote = positions_quote.get(code, {})
            current_price = quote.get("price", 0)
            cost = pos.get("cost", 0) or pos.get("avg_cost", 0)
            profit_pct = ((current_price - cost) / cost * 100) if cost > 0 and current_price > 0 else 0
            positions.append({
                "code": code,
                "name": pos.get("name", pos.get("stock_name", code)),
                "shares": pos.get("shares", 0),
                "cost": cost,
                "current_price": current_price,
                "profit_loss_pct": profit_pct,
            })

    can_build = False
    if index_data:
        price = index_data.get("price", 0)
        ma5 = index_data.get("ma5", 0)
        ma10 = index_data.get("ma10", 0)
        can_build = price > ma5 > 0 and ma5 > ma10 > 0

    return jsonify({
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "engine": {
            "phase": "idle",
            "description": "🥚 蛋蛋交易引擎就绪",
        },
        "market": {
            "code": index_data.get("code", "000001") if index_data else "000001",
            "name": index_data.get("name", "上证指数") if index_data else "上证指数",
            "price": index_data.get("price", 0) if index_data else 0,
            "ma5": index_data.get("ma5", 0) if index_data else 0,
            "ma10": index_data.get("ma10", 0) if index_data else 0,
            "can_build_position": bool(can_build),
        } if index_data else None,
        "account": {
            "cash": portfolio.get("cash", 0) if portfolio else 0,
            "total_value": portfolio.get("total_value", 0) if portfolio else 0,
            "positions_count": len(positions),
        },
        "positions": positions,
    })


@engine_bp.route('/api/engine/run', methods=['POST'])
def engine_run():
    """执行完整交易周期（增强版）"""
    try:
        from openclaw.indicators import calculate_rsi

        index_data = _get_index_data_cached()
        if not index_data:
            return jsonify({"success": False, "error": "无法获取大盘数据"}), 500

        price = index_data.get("price", 0)
        ma5 = index_data.get("ma5", 0)
        ma10 = index_data.get("ma10", 0)
        can_build = price > ma5 > 0 and ma5 > ma10 > 0

        portfolio = _get_portfolio_cached()
        if not portfolio:
            return jsonify({"success": False, "error": "无法获取账户数据"}), 500

        cash = portfolio.get("cash", 0)
        positions_data = portfolio.get("positions", {})

        # 获取持仓实时行情
        positions_quote = {}
        if positions_data:
            codes = list(positions_data.keys())
            code_str = ','.join(['sh'+c if c.startswith(('6', '5')) else 'sz'+c for c in codes])
            url = f"https://qt.gtimg.cn/q={code_str}"
            try:
                r = requests.get(url, timeout=3)
                for line in r.text.strip().split('\n'):
                    if '=' in line:
                        parts = line.split('="')
                        if len(parts) < 2:
                            continue
                        fields = parts[1].strip('"').split('~')
                        if len(fields) > 10:
                            code = fields[0]
                            for prefix in ['v_szh', 'v_shsh', 'sz', 'sh']:
                                code = code.replace(prefix, '')
                            positions_quote[code] = {
                                "price": float(fields[3]) if fields[3] != '-' else 0,
                                "change_pct": float(fields[32]) if len(fields) > 32 and fields[32] != '-' else 0,
                            }
            except Exception as e:
                logger.warning(f"获取持仓行情失败: {e}")

        # 分析持仓
        actions = []
        alerts = []

        for code, pos in positions_data.items():
            quote = positions_quote.get(code, {})
            current_price = quote.get("price", 0)
            cost = pos.get("cost", 0) or pos.get("avg_cost", 0)
            shares = pos.get("shares", 0)

            if cost > 0 and current_price > 0:
                profit_pct = (current_price - cost) / cost * 100
                loss_pct = -profit_pct

                # 止损检查（亏损3%）
                if loss_pct >= 3:
                    actions.append({
                        "action": "SELL",
                        "code": code,
                        "name": pos.get("name", pos.get("stock_name", code)),
                        "shares": shares,
                        "reason": f"🚨 止损！亏损 {loss_pct:.2f}%",
                        "priority": 1,
                        "urgent": True,
                    })
                    alerts.append(f"{pos.get('name', pos.get('stock_name', code))} 触发止损！亏损 {-loss_pct:.2f}%")
                    continue

                # 止盈检查（+3%~5%全仓卖出）
                if profit_pct >= 3:
                    actions.append({
                        "action": "SELL",
                        "code": code,
                        "name": pos.get("name", pos.get("stock_name", code)),
                        "shares": shares,
                        "reason": f"💰 止盈！盈利 {profit_pct:.2f}%",
                        "priority": 2,
                        "urgent": False,
                    })

                # RSI超买预警
                try:
                    symbol = f"sh{code}" if code.startswith(('6', '5')) else f"sz{code}"
                    df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq").tail(20)
                    if len(df) >= 15:
                        prices = df['收盘'].tolist()
                        rsi = calculate_rsi(prices)
                        if rsi and rsi > 70:
                            alerts.append(f"{pos.get('name', pos.get('stock_name', code))} RSI={rsi}，注意超买风险！")
                except Exception as e:
                    logger.warning(f"RSI计算失败 {code}: {e}")

        # 检查建仓条件
        if can_build and not actions and cash >= 10000:
            market_top = get_market_top_cached()
            if market_top:
                for item in market_top[:10]:
                    code = item.get("code", "")
                    change_pct = item.get("change_pct", 0)
                    volume = item.get("volume", 0)

                    if code not in positions_data:
                        if abs(change_pct) > 1.5 and volume > 500000:
                            actions.append({
                                "action": "BUY",
                                "code": code,
                                "name": item.get("name", code),
                                "shares": 100,
                                "reason": f"📈 放量突破！{'上涨' if change_pct > 0 else '下跌'} {change_pct:.2f}%，买入信号",
                                "priority": 5,
                                "urgent": False,
                            })
                            break

        # 输出分析报告（仅信号，不执行交易，交易由cron通过/api/trade执行）
        report = {
            "success": True,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "market": {
                "price": float(price),
                "ma5": float(ma5),
                "ma10": float(ma10),
                "can_build": bool(can_build),
            },
            "account": {
                "cash": float(cash),
                "positions_count": len(positions_data),
            },
            "analysis": {
                "stop_loss_triggered": sum(1 for a in actions if "止损" in a.get("reason", "")),
                "take_profit_triggered": sum(1 for a in actions if "止盈" in a.get("reason", "")),
                "buy_signals": sum(1 for a in actions if a["action"] == "BUY"),
                "alerts": alerts,
            },
            "actions_planned": len(actions),
            "actions": actions,
        }

        return jsonify(report)

    except Exception as e:
        import traceback
        logger.error(f"引擎运行失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


@engine_bp.route('/api/market/scan', methods=['GET'])
def market_scan():
    """盘中监控核心接口 - 智能决策版本"""
    try:
        from openclaw.indicators import calculate_rsi

        result = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "scan_mode": "auto",
            "index": None,
            "positions": [],
            "signals": [],
            "actions": [],
            "executed": [],
        }

        # 大盘检查
        try:
            index_url = "https://qt.gtimg.cn/q=sh000001"
            r = requests.get(index_url, timeout=3)
            fields = r.text.split('="')[1].strip('"').split('~')
            price = float(fields[3]) if fields[3] != '-' else 0

            try:
                df = ak.stock_zh_index_daily(symbol='sh000001')
                closes = df['close'].tail(20).tolist()
                ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0
                ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else 0
            except Exception:
                ma5 = ma10 = 0

            can_build = price > ma5 > 0 and ma5 > ma10 > 0

            result["index"] = {
                "name": "上证指数",
                "price": price,
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "above_ma5": price > ma5 > 0,
                "ma5_above_ma10": ma5 > ma10 > 0,
                "can_build": can_build,
            }
        except Exception as e:
            result["index"] = {"error": str(e)}

        # 账户和持仓
        portfolio = _get_portfolio_cached()
        cash = portfolio.get("cash", 0) if portfolio else 0
        positions_data = portfolio.get("positions", {}) if portfolio else {}

        result["account"] = {
            "cash": cash,
            "positions_count": len(positions_data),
        }

        # 持仓检查
        if positions_data:
            codes = list(positions_data.keys())
            code_str = ','.join(['sh'+c if c.startswith(('6', '5')) else 'sz'+c for c in codes])
            url = f"https://qt.gtimg.cn/q={code_str}"
            try:
                r = requests.get(url, timeout=3)

                for line in r.text.strip().split('\n'):
                    if '=' not in line:
                        continue
                    parts = line.split('="')
                    if len(parts) < 2:
                        continue
                    fields = parts[1].strip('"').split('~')
                    if len(fields) < 10:
                        continue

                    code = fields[0]
                    for prefix in ['v_szh', 'v_shsh', 'sz', 'sh']:
                        code = code.replace(prefix, '')

                    if code not in positions_data:
                        continue

                    pos = positions_data[code]
                    current_price = float(fields[3]) if fields[3] != '-' else 0
                    change_pct = float(fields[32]) if len(fields) > 32 and fields[32] != '-' else 0
                    cost = pos.get("cost", 0) or pos.get("avg_cost", 0)
                    shares = pos.get("shares", 0)

                    if cost <= 0 or current_price <= 0:
                        continue

                    profit_pct = (current_price - cost) / cost * 100
                    loss_pct = -profit_pct

                    # RSI 计算
                    rsi_value = None
                    try:
                        symbol = f"sh{code}" if code.startswith(('6', '5')) else f"sz{code}"
                        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq").tail(20)
                        if len(df) >= 15:
                            prices = df['收盘'].tolist()
                            rsi_value = calculate_rsi(prices)
                    except Exception:
                        pass

                    pos_result = {
                        "code": code,
                        "name": pos.get("name", pos.get("stock_name", code)),
                        "price": current_price,
                        "cost": cost,
                        "profit_pct": profit_pct,
                        "rsi": rsi_value,
                        "signals": [],
                        "action": None,
                    }

                    # 止损信号
                    if loss_pct >= 3:
                        pos_result["signals"].append({"type": "STOP_LOSS", "value": loss_pct, "urgent": True})
                        pos_result["action"] = "SELL"
                    elif profit_pct >= 3:
                        pos_result["signals"].append({"type": "TAKE_PROFIT", "value": profit_pct, "urgent": False})
                        pos_result["action"] = "SELL"

                    if rsi_value and rsi_value > 70:
                        pos_result["signals"].append({"type": "RSI_OVERBOUGHT", "value": rsi_value, "urgent": False})
                    if rsi_value and rsi_value < 35:
                        pos_result["signals"].append({"type": "RSI_OVERSOLD", "value": rsi_value, "urgent": True})

                    result["positions"].append(pos_result)

                    if pos_result["action"]:
                        result["actions"].append({
                            "action": pos_result["action"],
                            "code": code,
                            "name": pos_result["name"],
                            "shares": shares,
                            "reason": f"{pos_result['signals'][0]['type']} {pos_result['signals'][0]['value']:.1f}%",
                            "urgent": pos_result["signals"][0].get("urgent", False),
                        })
            except Exception as e:
                logger.warning(f"持仓检查失败: {e}")

        # 找新买入机会（一夜持股法 - 仅输出信号，不执行交易）
        now_hour = datetime.now().hour
        now_min = datetime.now().minute
        in_buy_window = (now_hour == 14 and 30 <= now_min <= 55)

        if in_buy_window and not result["actions"] and not positions_data:
            try:
                from strategies.overnight_strategy import OvernightStrategy
                s = OvernightStrategy(strategy_id=1)
                candidates = s.scan_stocks()
                if candidates:
                    best = candidates[0]
                    result["signals"].append({
                        "type": "BUY_OPPORTUNITY",
                        "code": best.get('code', ''),
                        "name": best.get('name', ''),
                        "change_pct": best.get('change_pct', 0),
                        "score": best.get('score', 0),
                    })
            except Exception as e:
                logger.warning(f"选股失败: {e}")

        # 最终决定（仅输出信号，交易由cron通过/api/trade执行）
        if result["actions"]:
            action_summary = [f"{a['action']} {a['name']}({a['code']})" for a in result["actions"]]
            result["decision"] = f"信号: {', '.join(action_summary)}"
        elif in_buy_window:
            result["decision"] = "观望 - 买入窗口内，暂无符合条件个股"
        else:
            result["decision"] = f"等待 - 买入窗口14:30-14:55，当前{datetime.now().strftime('%H:%M')}"

        return jsonify({"success": True, **result})

    except Exception as e:
        import traceback
        logger.error(f"盘中监控失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500
