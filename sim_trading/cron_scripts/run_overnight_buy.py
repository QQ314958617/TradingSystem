#!/usr/bin/env python3
"""
一夜持股法 - 尾盘买入执行 (14:55)
基于scan结果的前5名买入
"""
import urllib.request
import json
import sys

API_BASE = "http://localhost/api"

def api_get(path):
    url = f"{API_BASE}{path}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def api_post(path, data):
    url = f"{API_BASE}{path}"
    body = json.dumps(data).encode()
    try:
        req = urllib.request.Request(url, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def main():
    print(f"[{__file__}] 开始一夜持股法尾盘买入执行...", flush=True)
    
    # 查当前策略1持仓
    portfolio = api_get("/portfolio?strategy_id=1")
    if "error" in portfolio:
        print(f"[ERROR] 查持仓失败: {portfolio['error']}", flush=True)
        return 1
    
    positions = portfolio.get("positions", {})
    if not isinstance(positions, dict):
        positions = {}
    
    print(f"策略1当前持仓: {len(positions)} 只", flush=True)
    for code, pos in positions.items():
        print(f"  {code} {pos.get('stock_name','')} {pos.get('shares',0)}股 @{pos.get('avg_cost',0)}", flush=True)
    
    # 计算已用资金
    used_capital = sum(p.get('shares',0) * p.get('avg_cost',0) for p in positions.values())
    remaining_capital = 150000 - used_capital
    print(f"策略1已用: ¥{used_capital:.0f}, 剩余额度: ¥{remaining_capital:.0f}, 上限: ¥150,000", flush=True)
    
    if remaining_capital <= 0:
        print("策略1额度已用完，跳过买入", flush=True)
        return 0
    
    if len(positions) >= 3:
        print("策略1持仓已满3只，跳过买入", flush=True)
        return 0
    
    # 读取扫描结果
    try:
        with open("/tmp/overnight_scan_result.json") as f:
            scan_result = json.load(f)
    except FileNotFoundError:
        print("[ERROR] 未找到扫描结果文件 /tmp/overnight_scan_result.json", flush=True)
        return 1
    
    candidates = scan_result.get("results", [])
    if not candidates:
        print("扫描结果为空，跳过买入", flush=True)
        return 0
    
    # 前3名买入（一夜持股法最多3只），但不超过剩余额度
    max_new = 3 - len(positions)
    to_buy = candidates[:max_new]
    print(f"\n准备买入 {len(to_buy)} 只 (还可建仓{max_new}只):", flush=True)
    
    # 资金：剩余额度平分
    per_stock_max = min(50000, remaining_capital / max(1, max_new))
    
    for r in to_buy:
        code = r["code"]
        price = r["price"]
        name = r["name"]
        
        if price <= 0:
            print(f"  跳过 {code} {name}: 无效价格 {price}", flush=True)
            continue
        
        shares = int(per_stock_max / price / 100) * 100
        if shares < 100:
            print(f"  跳过 {code} {name}: 金额不足1手", flush=True)
            continue
        
        # 查实时行情
        quote = api_get(f"/quote/{code}")
        if "error" in quote:
            print(f"  跳过 {code} {name}: 查询行情失败", flush=True)
            continue
        
        cur_price = quote.get("price", price)
        change_pct = quote.get("change_pct", r.get("change_pct", 0))
        
        # 买入逻辑：涨幅退潮到3%以下的放弃
        if change_pct < 3.0:
            print(f"  跳过 {code} {name}: 涨幅回落至 {change_pct}%", flush=True)
            continue
        
        trade = {
            "action": "buy",
            "stock_code": code,
            "shares": shares,
            "price": cur_price,
            "reason": f"一夜持股法尾盘买入(评分{r.get('score',0)} 热力{r.get('heat_score',0)})",
            "strategy_id": 1
        }
        
        print(f"  买入 {code} {name} {shares}股 @{cur_price} (涨幅+{change_pct}%)", flush=True)
        result = api_post("/trade", trade)
        
        if "error" in result:
            print(f"  买入失败: {result['error']}", flush=True)
        else:
            print(f"  买入成功! trade_id={result.get('id','N/A')}", flush=True)
    
    print(f"\n买入执行完成", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
