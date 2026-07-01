#!/usr/bin/env python3
"""小市值策略 - 每日检查止损 + 每周二调仓"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from datetime import datetime
from strategies.small_cap_strategy import small_cap_scan, check_stop_loss

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger('small_cap')

API_BASE = "http://localhost/api"

def api_post(path, data):
    import urllib.request
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{API_BASE}{path}", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def api_get(path):
    import urllib.request
    req = urllib.request.Request(f"{API_BASE}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def get_current_prices(codes):
    """批量获取当前价格"""
    prices = {}
    for code in codes:
        try:
            q = api_get(f"/quote/{code}")
            if 'price' in q and q['price'] > 0:
                prices[code] = q['price']
        except Exception:
            pass
    return prices

def main():
    is_tuesday = datetime.now().weekday() == 1
    do_adjust = is_tuesday
    
    logger.info(f"[小市值] {'周二调仓日' if do_adjust else '非调仓日'} 开始执行")
    
    # 查当前持仓
    portfolio = api_get("/portfolio?strategy_id=2")
    positions = portfolio.get("positions", {})
    pos_list = [{
        'stock_code': k, 'stock_name': v.get('stock_name', ''),
        'shares': v['shares'], 'avg_cost': v['avg_cost'],
    } for k, v in positions.items()]
    
    logger.info(f"当前持仓: {len(pos_list)} 只")
    
    if not pos_list:
        if do_adjust:
            logger.info("无持仓，执行建仓")
        else:
            logger.info("无持仓，跳过")
    
    # 止损检查（每天执行）
    codes = [p['stock_code'] for p in pos_list]
    current_prices = get_current_prices(codes)
    stop_positions = check_stop_loss(pos_list, current_prices)
    
    for pos in stop_positions:
        logger.info(f"止损 {pos['stock_code']} {pos.get('stock_name','')} {pos['shares']}股")
        result = api_post("/trade", {
            "action": "sell", "stock_code": pos['stock_code'],
            "shares": pos['shares'],
            "reason": "小市值止损",
            "strategy_id": 2
        })
        if "error" in result:
            logger.error(f"止损卖出失败: {result['error']}")
        else:
            logger.info(f"止损成功")
    
    # 周二调仓
    if do_adjust:
        # 重新获取持仓
        portfolio = api_get("/portfolio?strategy_id=2")
        positions = portfolio.get("positions", {})
        current_codes = list(positions.keys())
        
        # 扫描目标
        targets = small_cap_scan()
        target_codes = [t['code'] for t in targets[:6]]  # 持6只
        
        logger.info(f"调仓目标(前6): {target_codes}")
        
        # 卖出不在目标的
        for code in current_codes:
            if code not in target_codes:
                pos = positions[code]
                # 检查是否昨日涨停
                logger.info(f"卖出 {code} {pos.get('stock_name','')} {pos['shares']}股")
                result = api_post("/trade", {
                    "action": "sell", "stock_code": code,
                    "shares": pos['shares'],
                    "reason": "小市值调仓换股",
                    "strategy_id": 2
                })
                if "error" in result:
                    logger.error(f"卖出{code}失败: {result['error']}")
                else:
                    logger.info(f"卖出成功")
        
        # 买入新目标
        portfolio = api_get("/portfolio?strategy_id=2")
        pos_after = portfolio.get("positions", {})
        current_after = list(pos_after.keys())
        
        strategy_capital = 35000.0
        used = sum(p['shares'] * p['avg_cost'] for p in pos_after.values())
        available = max(0, strategy_capital - used)
        target_count = 6 - len(current_after)
        
        if target_count > 0 and available > 0:
            per_stock = available / target_count
            for t in targets:
                code = t['code']
                if code in current_after:
                    continue
                if per_stock < t['price'] * 100:
                    break
                shares = int(per_stock / t['price'] / 100) * 100
                if shares >= 100:
                    logger.info(f"买入 {t['name']}({code}) {shares}股 @{t['price']}")
                    result = api_post("/trade", {
                        "action": "buy", "stock_code": code,
                        "shares": shares,
                        "reason": "小市值轮动建仓",
                        "strategy_id": 2
                    })
                    if "error" in result:
                        logger.error(f"买入{code}失败: {result['error']}")
                    else:
                        logger.info(f"买入成功")
    
    logger.info("[小市值] 执行完成")
    return 0

if __name__ == "__main__":
    sys.exit(main())
