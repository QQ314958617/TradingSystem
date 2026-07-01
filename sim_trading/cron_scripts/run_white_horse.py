#!/usr/bin/env python3
"""白马策略 - 每日止损 + 每周调仓"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from datetime import datetime
from strategies.white_horse_strategy import white_horse_scan, check_stop_loss

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger('white_horse')

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
    logger.info(f"[白马] 开始执行")
    
    # 查当前持仓
    portfolio = api_get("/portfolio?strategy_id=3")
    positions = portfolio.get("positions", {})
    pos_list = [{
        'stock_code': k, 'stock_name': v.get('stock_name', ''),
        'shares': v['shares'], 'avg_cost': v['avg_cost'],
    } for k, v in positions.items()]
    
    logger.info(f"当前持仓: {len(pos_list)} 只")
    
    # 止损检查
    if pos_list:
        codes = [p['stock_code'] for p in pos_list]
        current_prices = get_current_prices(codes)
        stop_positions = check_stop_loss(pos_list, current_prices)
        
        for pos in stop_positions:
            logger.info(f"止损 {pos['stock_code']} {pos.get('stock_name','')} {pos['shares']}股")
            result = api_post("/trade", {
                "action": "sell", "stock_code": pos['stock_code'],
                "shares": pos['shares'],
                "reason": "白马止损",
                "strategy_id": 3
            })
            if "error" in result:
                logger.error(f"止损卖出失败: {result['error']}")
            else:
                logger.info(f"止损成功")
    
    # 检查是否到调仓周期（每周一）
    is_monday = datetime.now().weekday() == 0
    if is_monday:
        logger.info("周一，执行白马调仓扫描")
        result = white_horse_scan()
        targets = result.get('targets', [])
        
        if not targets:
            logger.warning("白马扫描无结果")
            return 0
        
        # 重新获取持仓
        portfolio = api_get("/portfolio?strategy_id=3")
        positions = portfolio.get("positions", {})
        current_codes = list(positions.keys())
        target_codes = [t['code'] for t in targets[:20]]
        
        # 卖出不在目标
        for code in current_codes:
            if code not in target_codes:
                pos = positions[code]
                logger.info(f"卖出 {code} {pos.get('stock_name','')} {pos['shares']}股")
                api_post("/trade", {
                    "action": "sell", "stock_code": code,
                    "shares": pos['shares'],
                    "reason": "白马调仓换股",
                    "strategy_id": 3
                })
        
        # 买入
        portfolio = api_get("/portfolio?strategy_id=3")
        pos_after = portfolio.get("positions", {})
        
        strategy_capital = 25000.0
        used = sum(p['shares'] * p['avg_cost'] for p in pos_after.values())
        available = max(0, strategy_capital - used)
        
        if available > 0:
            target_count = 20 - len(pos_after)
            if target_count > 0:
                per_stock = available / target_count
                bought = 0
                for t in targets:
                    code = t['code']
                    if code in pos_after:
                        continue
                    if per_stock < t['price'] * 100:
                        break
                    shares = int(per_stock / t['price'] / 100) * 100
                    if shares >= 100:
                        logger.info(f"买入 {t['name']}({code}) {shares}股 @{t['price']}")
                        api_post("/trade", {
                            "action": "buy", "stock_code": code,
                            "shares": shares,
                            "reason": "白马建仓",
                            "strategy_id": 3
                        })
                        bought += 1
                        if bought >= target_count:
                            break
    
    logger.info("[白马] 执行完成")
    return 0

if __name__ == "__main__":
    sys.exit(main())
