#!/usr/bin/env python3
"""
价值投资每日止损扫描 (10:00 / 14:00)
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
    body = json.dumps(data).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def main():
    print(f"[{__file__}] 价值投资每日止损扫描...", flush=True)
    
    portfolio = api_get("/portfolio?strategy_id=2")
    if "error" in portfolio:
        print(f"[ERROR] {portfolio['error']}", flush=True)
        return 1
    
    positions = portfolio.get("positions", {}) or {}
    if not positions:
        print("策略2空仓", flush=True)
        return 0
    
    codes = ",".join(positions.keys())
    quotes = api_get(f"/quotes/batch?codes={codes}")
    if "error" in quotes:
        print(f"[ERROR] 行情查询失败: {quotes['error']}", flush=True)
        return 1
    
    sold_any = False
    for q in quotes:
        code = q["code"]
        if code not in positions:
            continue
        name = q.get("name", code)
        price = q["price"]
        pos = positions[code]
        cost = pos["avg_cost"]
        shares = pos["shares"]
        
        profit_pct = (price - cost) / cost * 100
        
        print(f"  {code} {name}: 成本{cost} 现价{price} 盈亏{profit_pct:+.2f}%", flush=True)
        
        # 止损：浮亏≥-7%
        if profit_pct <= -7:
            print(f"  -> 触发止损! (亏{profit_pct:.1f}% <= -7%)", flush=True)
            result = api_post("/trade", {
                "action": "sell",
                "stock_code": code,
                "shares": shares,
                "price": price,
                "reason": f"价值投资止损(亏{profit_pct:.1f}%)",
                "strategy_id": 2
            })
            if "error" in result:
                print(f"  -> 卖出失败: {result['error']}", flush=True)
            else:
                print(f"  -> 止损成功!", flush=True)
                sold_any = True
        # 止盈：浮盈≥+25%
        elif profit_pct >= 25:
            print(f"  -> 触发清仓! (盈{profit_pct:.1f}% >= +25%)", flush=True)
            result = api_post("/trade", {
                "action": "sell",
                "stock_code": code,
                "shares": shares,
                "price": price,
                "reason": f"价值投资清仓(盈{profit_pct:.1f}%)",
                "strategy_id": 2
            })
            if "error" in result:
                print(f"  -> 卖出失败: {result['error']}", flush=True)
            else:
                print(f"  -> 清仓成功!", flush=True)
                sold_any = True
        # 半仓止盈：浮盈≥+15%
        elif profit_pct >= 15:
            half = shares // 2
            if half >= 100:
                print(f"  -> 触发半仓止盈! (盈{profit_pct:.1f}% >= +15%)", flush=True)
                result = api_post("/trade", {
                    "action": "sell",
                    "stock_code": code,
                    "shares": half,
                    "price": price,
                    "reason": f"价值投资半仓止盈(盈{profit_pct:.1f}%)",
                    "strategy_id": 2
                })
                if "error" in result:
                    print(f"  -> 卖出失败: {result['error']}", flush=True)
                else:
                    print(f"  -> 半仓止盈成功!", flush=True)
                    sold_any = True
            else:
                print(f"  -> 浮盈{profit_pct:.1f}%但不足1手，持有", flush=True)
        else:
            print(f"  -> 正常持有", flush=True)
    
    if sold_any:
        print("\n有止损/止盈操作", flush=True)
    else:
        print("\n无操作", flush=True)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
