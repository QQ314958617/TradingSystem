#!/usr/bin/env python3
"""
每日复盘推送 (15:30)
生成复盘报告并写入数据库
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
    print(f"[{__file__}] 每日复盘 {today}", flush=True)
    
    # 1. 查账户
    portfolio = api_get("/portfolio")
    if "error" in portfolio:
        print(f"[ERROR] 查账户失败: {portfolio['error']}", flush=True)
        return 1
    
    total_value = portfolio.get("total_value", 0)
    cash = portfolio.get("cash", 0)
    total_profit = portfolio.get("total_profit", 0)
    initial_capital = portfolio.get("initial_capital", 500000)
    positions = portfolio.get("positions", {}) or {}
    
    profit_pct = total_profit / initial_capital * 100
    pos_count = len(positions)
    
    print(f"总资产: {fmt_price(total_value)} | 现金: {fmt_price(cash)} | 盈亏: {fmt_price(total_profit)} ({profit_pct:+.2f}%) | 持仓: {pos_count} 只", flush=True)
    
    # 2. 查今日交易
    trades = api_get("/trades?page_size=50")
    if "error" in trades:
        print(f"[WARN] 查交易记录失败: {trades['error']}", flush=True)
        trades = []
    else:
        trades = trades if isinstance(trades, list) else trades.get("trades", [])
    
    # 过滤今天的交易
    today_trades = [t for t in trades if isinstance(t, dict) and t.get("trade_date", "").startswith(today)]
    
    # 3. 分类各策略数据
    # 查各策略持仓
    s1_positions = api_get("/portfolio?strategy_id=1") if pos_count > 0 else {"positions": {}}
    s2_positions = api_get("/portfolio?strategy_id=2") if pos_count > 0 else {"positions": {}}
    s3_positions = api_get("/portfolio?strategy_id=3") if pos_count > 0 else {"positions": {}}
    
    s1_pos = s1_positions.get("positions", {}) or {}
    s2_pos = s2_positions.get("positions", {}) or {}
    s3_pos = s3_positions.get("positions", {}) or {}
    
    # 4. 生成复盘内容
    lines = []
    lines.append(f"## 🥚 蛋蛋基金每日复盘 {today}")
    lines.append("")
    lines.append(f"### 📊 账户概览")
    lines.append(f"总资产：{fmt_price(total_value)} | 现金：{fmt_price(cash)} | 累计盈亏：{fmt_price(total_profit)}（{profit_pct:+.2f}%）")
    lines.append(f"持仓：{pos_count} 只")
    lines.append("")
    
    if today_trades:
        lines.append(f"### 📝 今日交易 ({len(today_trades)} 笔)")
        for t in today_trades:
            action = t.get("action", "")
            code = t.get("stock_code", "")
            name = t.get("stock_name", "")
            shares = t.get("shares", 0)
            price = t.get("price", 0)
            sname = t.get("strategy_name", f"策略{t.get('strategy_id','?')}")
            profit = t.get("profit", 0)
            action_icon = "🟢" if action == "buy" or (action == "sell" and profit >= 0) else "🔴"
            profit_str = f"{profit:+.0f}" if profit != 0 else ""
            lines.append(f"{action_icon} {action} {code} {name} {shares}股@{price} {profit_str} [{sname}]")
        lines.append("")
    
    lines.append("### 📋 各策略持仓")
    
    if s1_pos:
        lines.append(f"\n**🟡 一夜持股法 (策略1)**")
        for code, p in s1_pos.items():
            lines.append(f"- {code} {p.get('stock_name','')} {p.get('shares',0)}股 @{p.get('avg_cost',0)}")
    if s2_pos:
        lines.append(f"\n**🟢 价值投资 (策略2)**")
        for code, p in s2_pos.items():
            lines.append(f"- {code} {p.get('stock_name','')} {p.get('shares',0)}股 @{p.get('avg_cost',0)}")
    if s3_pos:
        lines.append(f"\n**🔵 趋势跟踪 (策略3)**")
        for code, p in s3_pos.items():
            lines.append(f"- {code} {p.get('stock_name','')} {p.get('shares',0)}股 @{p.get('avg_cost',0)}")
    
    if not s1_pos and not s2_pos and not s3_pos:
        lines.append("空仓")
    
    lines.append("")
    
    # 5. 标注datetime
    now = datetime.now()
    lines.append(f"---")
    lines.append(f"复盘时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"系统状态：{'🔴 有亏损' if total_profit < 0 else '🟢 盈利中'}")
    
    content = "\n".join(lines)
    
    # 6. 写入数据库
    strategies = []
    if s1_pos: strategies.append("一夜持股法")
    if s2_pos: strategies.append("价值投资")
    if s3_pos: strategies.append("趋势跟踪")
    
    review_data = {
        "content": content,
        "tags": ["daily"],
        "strategies": strategies
    }
    
    result = api_post("/review", review_data)
    if "error" in result:
        print(f"[ERROR] 复盘写入失败: {result['error']}", flush=True)
        return 1
    
    print(f"\n复盘报告已写入 (id={result.get('id','?')})", flush=True)
    
    # 7. 输出摘要（cron delivery会capture这个输出）
    print("\n" + "=" * 60, flush=True)
    print(f"🥚【每日复盘摘要】{today}", flush=True)
    print(f"总资产: {fmt_price(total_value)} | 盈亏: {fmt_price(total_profit)} ({profit_pct:+.2f}%)", flush=True)
    if today_trades:
        print(f"今日交易: {len(today_trades)} 笔", flush=True)
        for t in today_trades:
            profit = t.get("profit", 0)
            profit_str = f" (盈亏:{profit:+.0f})" if profit != 0 else ""
            print(f"  {t.get('action','?')} {t.get('stock_code','')} {t.get('stock_name','')} {t.get('shares',0)}股{t.get('price',0)} {profit_str}", flush=True)
    lines.append(f"持仓: {pos_count} 只")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
