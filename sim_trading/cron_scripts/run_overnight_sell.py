#!/usr/bin/env python3
"""
早盘卖出扫描 (策略1 - 一夜持股法)
每隔5分钟执行一次，检查持仓是否需要卖出
"""
import urllib.request
import json
import sys

API_BASE = "http://localhost/api"

def api_get(path):
    url = f"{API_BASE}{path}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def api_post(path, data):
    url = f"{API_BASE}{path}"
    body = json.dumps(data).encode()
    try:
        req = urllib.request.Request(url, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def main():
    print(f"[{__file__}] 早盘卖出扫描...", flush=True)
    
    # 查策略1持仓
    portfolio = api_get("/portfolio?strategy_id=1")
    if "error" in portfolio:
        print(f"[ERROR] {portfolio['error']}", flush=True)
        return 1
    
    positions = portfolio.get("positions", {})
    if not isinstance(positions, dict):
        positions = {}
    
    if not positions:
        print("策略1空仓，跳过", flush=True)
        return 0
    
    codes = ",".join(positions.keys())
    quotes = api_get(f"/quotes/batch?codes={codes}")
    if "error" in quotes:
        print(f"[ERROR] 批量行情查询失败: {quotes['error']}", flush=True)
        return 1
    
    sold_any = False
    for q in quotes:
        code = q["code"]
        if code not in positions:
            continue
        name = q.get("name", code)
        price = q["price"]
        change_pct = q.get("change_pct", 0)
        pos = positions[code]
        cost = pos["avg_cost"]
        shares = pos["shares"]
        
        profit_pct = (price - cost) / cost * 100
        
        print(f"  {code} {name}: 成本{cost} 现价{price} 涨幅{change_pct:+.2f}% 盈亏{profit_pct:+.2f}%", flush=True)
        
        # v3.3规则
        if profit_pct <= -3.5:
            # 止损
            print(f"  -> 触发止损! (跌{-profit_pct:.2f}%超过-3.5%)", flush=True)
            result = api_post("/trade", {
                "action": "sell",
                "stock_code": code,
                "shares": shares,
                "price": price,
                "reason": f"一夜持股法止损(跌{profit_pct:.1f}%)",
                "strategy_id": 1
            })
            if "error" in result:
                print(f"  -> 卖出失败: {result['error']}", flush=True)
            else:
                print(f"  -> 止损成功!", flush=True)
                sold_any = True
        elif profit_pct >= 8:
            # 涨8%直接走
            print(f"  -> 触发止盈! (+{profit_pct:.2f}% 超过+8%)", flush=True)
            result = api_post("/trade", {
                "action": "sell",
                "stock_code": code,
                "shares": shares,
                "price": price,
                "reason": f"一夜持股法止盈(涨{profit_pct:.1f}%)",
                "strategy_id": 1
            })
            if "error" in result:
                print(f"  -> 卖出失败: {result['error']}", flush=True)
            else:
                print(f"  -> 止盈成功!", flush=True)
                sold_any = True
        elif profit_pct >= 4:
            # 涨幅4%以上但不到8%，盘中冲高回落超过2%就卖
            high = q.get("high", price)
            if high > 0 and (high - price) / high * 100 >= 2:
                print(f"  -> 冲高回落{ (high-price)/high*100:.1f}% 超过2%，卖出", flush=True)
                result = api_post("/trade", {
                    "action": "sell",
                    "stock_code": code,
                    "shares": shares,
                    "price": price,
                    "reason": f"一夜持股法冲高回落止盈(高{high}→现{price})",
                    "strategy_id": 1
                })
                if "error" in result:
                    print(f"  -> 卖出失败: {result['error']}", flush=True)
                else:
                    print(f"  -> 卖出成功!", flush=True)
                    sold_any = True
            else:
                print(f"  -> 持有(涨幅{profit_pct:.1f}% 高位{high} 回落{(high-price)/high*100:.1f}%)", flush=True)
        else:
            print(f"  -> 继续观察", flush=True)
    
    if sold_any:
        print("\n有卖出操作", flush=True)
    else:
        print("\n无卖出操作", flush=True)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
