#!/usr/bin/env python3
"""
每日复盘推送 (15:30) v2.0
适配新三策略（ETF轮动/小市值/白马）
"""
import urllib.request
import json
import sys
from datetime import datetime

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
    body = json.dumps(data).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def fmt_price(v):
    return f"¥{v:,.2f}"

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[复盘] 每日复盘 {today}", flush=True)
    
    # 查dashboard数据
    dashboard = api_get("/dashboard?t=" + str(int(datetime.now().timestamp())))
    if "error" in dashboard:
        print(f"[ERROR] 查失败: {dashboard['error']}", flush=True)
        return 1
    
    account = dashboard.get("account", {})
    total_value = account.get("total_value", 0)
    cash = account.get("cash", 0)
    total_profit = account.get("total_profit", 0)
    initial_capital = account.get("initial_capital", 100000)
    positions = dashboard.get("positions", {}) or {}
    strategies = dashboard.get("strategies", {}) or {}
    
    profit_pct = total_profit / initial_capital * 100 if initial_capital > 0 else 0
    pos_count = len(positions)
    
    # 今日交易
    trades = dashboard.get("trades", []) or []
    today_trades = [t for t in trades if isinstance(t, dict) and t.get("trade_date", "").startswith(today)]
    
    # 生成复盘
    lines = []
    lines.append(f"## 🥚 蛋蛋基金每日复盘 {today}")
    lines.append("")
    lines.append(f"### 📊 账户概览")
    lines.append(f"总资产：{fmt_price(total_value)} | 现金：{fmt_price(cash)} | 盈亏：{fmt_price(total_profit)}（{profit_pct:+.2f}%）")
    lines.append(f"持仓：{pos_count} 只")
    lines.append("")
    
    # 三策略状态
    lines.append("### 🎯 三策略状态")
    strategy_names = {'etf': 'ETF轮动', 'small_cap': '小市值', 'white_horse': '白马'}
    for skey, sname in strategy_names.items():
        sd = strategies.get(skey, {})
        if sd:
            lines.append(f"- **{sname}**: 分配{sd.get('capital_allocated',0):.0f} 已用{sd.get('capital_used',0):.0f} 持仓{sd.get('position_count',0)}只 盈亏{sd.get('profit',0):+.0f}")
        else:
            lines.append(f"- **{sname}**: 等待启动")
    
    lines.append("")
    
    if today_trades:
        lines.append(f"### 📝 今日交易 ({len(today_trades)} 笔)")
        for t in today_trades:
            action = t.get("action", "")
            code = t.get("stock_code", "")
            name = t.get("stock_name", "")
            shares = t.get("shares", 0)
            price = t.get("price", 0)
            profit = t.get("profit", 0)
            sid = t.get("strategy_id", 0)
            sn = {1:'ETF轮动', 2:'小市值', 3:'白马'}.get(sid, f'策略{sid}')
            action_icon = "🟢" if action == "buy" or (action == "sell" and profit >= 0) else "🔴"
            profit_str = f"盈亏:{profit:+.0f}" if profit != 0 else ""
            lines.append(f"{action_icon} {action} {code} {name} {shares}股@{price} {profit_str} [{sn}]")
        lines.append("")
    
    # 持仓详情
    if positions:
        lines.append("### 📋 当前持仓")
        for code, p in positions.items():
            lines.append(f"- {code} {p.get('stock_name','')} {p.get('shares',0)}股 成本{p.get('avg_cost',0)} 现价{p.get('current_price',0)}")
    else:
        lines.append("空仓")
    
    lines.append("")
    lines.append(f"---")
    lines.append(f"复盘时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    content = "\n".join(lines)
    
    # 写入复盘
    # 查策略持仓用于标签
    active_strategies = []
    for skey in ['etf', 'small_cap', 'white_horse']:
        sd = strategies.get(skey, {})
        if sd and sd.get('position_count', 0) > 0:
            stype = sd.get('type', skey)
            active_strategies.append(sd.get('name', skey))
    
    result = api_post("/review", {
        "content": content,
        "tags": ["daily", "v2.0"],
        "strategies": active_strategies if active_strategies else ["ETF轮动", "小市值", "白马"]
    })
    
    if "error" in result:
        print(f"[ERROR] 复盘写入失败: {result['error']}", flush=True)
        return 1
    
    print(f"\n✅ 复盘写入 (id={result.get('id','?')})", flush=True)
    
    # 摘要输出
    print("\n" + "=" * 60, flush=True)
    print(f"🥚【每日复盘摘要】{today}", flush=True)
    print(f"总资产: {fmt_price(total_value)} | 盈亏: {fmt_price(total_profit)} ({profit_pct:+.2f}%)", flush=True)
    if today_trades:
        print(f"今日交易: {len(today_trades)} 笔", flush=True)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
