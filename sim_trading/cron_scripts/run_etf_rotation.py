#!/usr/bin/env python3
"""ETF轮动策略 - 每日执行"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from strategies.etf_rotation import etf_rotation_scan, ETF_STRATEGY_CONFIG, ETF_NAMES

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger('etf_rotation')

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

def main():
    logger.info("[ETF轮动] 开始每日扫描")
    
    # 1. 扫描
    results = etf_rotation_scan()
    if not results:
        logger.warning("无符合条件的ETF")
        return 0
    
    best = results[0]
    logger.info(f"最佳ETF: {best['name']}({best['code']}) 评分:{best['score']}")
    
    # 2. 查当前持仓
    portfolio = api_get("/portfolio?strategy_id=1")
    positions = portfolio.get("positions", {})
    
    current_codes = list(positions.keys())
    logger.info(f"当前ETF持仓: {current_codes}")
    
    # 3. 卖出非目标ETF
    target_code = best['code']
    for code in current_codes:
        if code != target_code:
            pos = positions[code]
            logger.info(f"卖出 {code} {pos.get('stock_name','')} {pos['shares']}股")
            result = api_post("/trade", {
                "action": "sell", "stock_code": code,
                "shares": pos['shares'],
                "reason": "ETF轮动调仓：换入" + target_code,
                "strategy_id": 1
            })
            if "error" in result:
                logger.error(f"卖出{code}失败: {result['error']}")
            else:
                logger.info(f"卖出成功")
    
    # 4. 买入目标ETF（如果没有持仓）
    trading_codes = [c for c in current_codes if c in positions]
    if target_code not in trading_codes:
        # 计算可用资金
        strategy_total = 40000.0  # ETF轮动资金上限
        used = sum(p['shares'] * p['avg_cost'] for p in positions.values())
        available = max(0, strategy_total - used)
        
        if available > 0:
            shares = int(available / best['price'] / 100) * 100
            if shares >= 100:
                logger.info(f"买入 {best['name']}({best['code']}) {shares}股 @{best['price']}")
                result = api_post("/trade", {
                    "action": "buy", "stock_code": best['code'],
                    "shares": shares,
                    "reason": f"ETF轮动买入(评分{best['score']})",
                    "strategy_id": 1
                })
                if "error" in result:
                    logger.error(f"买入失败: {result['error']}")
                else:
                    logger.info(f"买入成功")
            else:
                logger.warning(f"资金不足1手: ¥{available} 价格{best['price']}")
        else:
            logger.info("资金已用完，跳过买入")
    else:
        logger.info(f"目标ETF {target_code} 已在持仓中，无需操作")
    
    logger.info("[ETF轮动] 执行完成")
    return 0

if __name__ == "__main__":
    sys.exit(main())
