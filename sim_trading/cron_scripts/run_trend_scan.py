#!/usr/bin/env python3
"""
趋势跟踪每日扫描 (10:00)
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
    print(f"[{__file__}] 趋势跟踪每日扫描...", flush=True)
    
    portfolio = api_get("/portfolio?strategy_id=3")
    if "error" in portfolio:
        print(f"[ERROR] {portfolio['error']}", flush=True)
        return 1
    
    positions = portfolio.get("positions", {}) or {}
    
    if positions:
        # 已有持仓，检查情况
        codes = ",".join(positions.keys())
        quotes = api_get(f"/quotes/batch?codes={codes}")
        if "error" not in quotes:
            from datetime import datetime
            now = datetime.now()
            for q in quotes:
                code = q["code"]
                name = q.get("name", code)
                price = q["price"]
                if code not in positions:
                    continue
                pos = positions[code]
                cost = pos["avg_cost"]
                shares = pos["shares"]
                profit_pct = (price - cost) / cost * 100
                
                # 计算持有天数
                buy_date_str = pos.get("buy_date", "") or ""
                hold_days = 0
                if buy_date_str:
                    try:
                        buy_dt = datetime.strptime(buy_date_str[:10], "%Y-%m-%d")
                        hold_days = (now - buy_dt).days
                    except:
                        pass
                
                print(f"  {code} {name}: 成本{cost} 现价{price} 盈亏{profit_pct:+.2f}% 持有{hold_days}天 {shares}股", flush=True)
                
                # 最大持有天数强制平仓
                if hold_days >= 14:
                    print(f"  -> 持有{hold_days}天达到14天上限，强制平仓!", flush=True)
                    result = api_post("/trade", {
                        "action": "sell",
                        "stock_code": code,
                        "shares": shares,
                        "price": price,
                        "reason": f"趋势跟踪超时卖出(持{hold_days}天)",
                        "strategy_id": 3
                    })
                    if "error" in result:
                        print(f"  -> 卖出失败: {result['error']}", flush=True)
                    else:
                        print(f"  -> 强制平仓成功!", flush=True)
                    continue
                
                # 止损 -6%
                    print(f"  -> 趋势跟踪止损! (亏{profit_pct:.1f}%)", flush=True)
                    result = api_post("/trade", {
                        "action": "sell",
                        "stock_code": code,
                        "shares": shares,
                        "price": price,
                        "reason": f"趋势跟踪止损(亏{profit_pct:.1f}%)",
                        "strategy_id": 3
                    })
                    if "error" in result:
                        print(f"  -> 卖出失败: {result['error']}", flush=True)
                    else:
                        print(f"  -> 止损成功!", flush=True)
                # 清仓止盈 +12%
                elif profit_pct >= 12:
                    print(f"  -> 趋势跟踪止盈! (盈{profit_pct:.1f}%)", flush=True)
                    result = api_post("/trade", {
                        "action": "sell",
                        "stock_code": code,
                        "shares": shares,
                        "price": price,
                        "reason": f"趋势跟踪止盈(盈{profit_pct:.1f}%)",
                        "strategy_id": 3
                    })
                    if "error" in result:
                        print(f"  -> 卖出失败: {result['error']}", flush=True)
                    else:
                        print(f"  -> 止盈成功!", flush=True)
                # 半仓止盈 +8%
                elif profit_pct >= 8:
                    half = shares // 2
                    if half >= 100:
                        print(f"  -> 半仓止盈! (盈{profit_pct:.1f}%)", flush=True)
                        result = api_post("/trade", {
                            "action": "sell",
                            "stock_code": code,
                            "shares": half,
                            "price": price,
                            "reason": f"趋势跟踪半仓止盈(盈{profit_pct:.1f}%)",
                            "strategy_id": 3
                        })
                        if "error" in result:
                            print(f"  -> 卖出失败: {result['error']}", flush=True)
                        else:
                            print(f"  -> 半仓止盈成功!", flush=True)
                    else:
                        print(f"  -> 浮盈{profit_pct:.1f}%但不足1手", flush=True)
                else:
                    print(f"  -> 持有中", flush=True)
        return 0
    
    # 空仓 - 用Python策略扫描
    print("策略3空仓，执行全市场趋势扫描...", flush=True)
    try:
        sys.path.insert(0, "/root/.openclaw/workspace/sim_trading")
        from strategies.trend_strategy import TrendFollowingStrategy
        s = TrendFollowingStrategy(3)
        results = s.scan_stocks()
        if results:
            print(f"扫描到 {len(results)} 只候选", flush=True)
            for r in results[:3]:
                print(f"  {r.get('code','')} {r.get('name','')} 评分={r.get('score','')}", flush=True)
        else:
            print("无趋势买入信号", flush=True)
    except Exception as e:
        print(f"[WARN] 策略扫描失败（非致命）: {e}", flush=True)
        print("使用API扫描...", flush=True)
        result = api_get("/screen/overnight")
        if "error" not in result and result.get("count", 0) > 0:
            top = result["results"][:5]
            print(f"API扫描到 {result['count']} 只, top5:", flush=True)
            for r in top:
                print(f"  {r['code']} {r['name']} +{r['change_pct']}%", flush=True)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
