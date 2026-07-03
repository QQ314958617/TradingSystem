#!/usr/bin/env python3
"""
每日复盘推送 — 15:30
生成当日交易总结，推送给用户
"""
import sys
import os
import json
import urllib.request
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger('run_review')

API_BASE = "http://localhost/api"


def api_get(path):
    req = urllib.request.Request(f"{API_BASE}{path}",
                                  headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def api_post(path, data):
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(f"{API_BASE}{path}", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fmt(v):
    return f"¥{v:,.0f}"


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"[复盘] 开始 {today}")

    # 获取账户+持仓
    portfolio = api_get(f"/portfolio?t={int(datetime.now().timestamp())}")
    account = portfolio
    cash = account.get('cash', 0)
    total_value = account.get('total_value', 0)
    total_profit = account.get('total_profit', 0)
    initial_capital = account.get('initial_capital', 300000)
    positions = account.get('positions', {})

    profit_pct = total_profit / initial_capital * 100 if initial_capital > 0 else 0

    # 今日交易记录
    trades_resp = api_get("/trades?page_size=100")
    all_trades = trades_resp.get('trades', [])
    today_trades = [t for t in all_trades if t.get('trade_date', '').startswith(today)]

    # 生成复盘内容
    lines = []
    lines.append(f"## 🥚 蛋蛋基金每日复盘 {today}")
    lines.append("")
    lines.append("### 📊 账户概览")
    lines.append(f"- 总资产: {fmt(total_value)}")
    lines.append(f"- 现金: {fmt(cash)}")
    lines.append(f"- 盈亏: {fmt(total_profit)} ({profit_pct:+.2f}%)")
    lines.append(f"- 持仓: {len(positions)} 只")
    lines.append("")

    # 今日交易
    if today_trades:
        lines.append(f"### 📝 今日交易 ({len(today_trades)} 笔)")
        for t in today_trades:
            action = t.get('action', '')
            code = t.get('stock_code', '')
            name = t.get('stock_name', '')
            shares = t.get('shares', 0)
            price = t.get('price', 0)
            profit = t.get('profit', 0)
            reason = t.get('reason', '')

            if action == 'buy':
                icon = "🟢"
                desc = f"买入 {code} {name} {shares}股 @{price:.2f}"
            else:
                icon = "🔴" if profit < 0 else "🟢"
                desc = f"卖出 {code} {name} {shares}股 @{price:.2f} 盈亏{profit:+.0f}元"

            lines.append(f"{icon} {desc}")
            if reason:
                lines.append(f"   理由: {reason}")
        lines.append("")

    # 当前持仓
    if positions:
        lines.append("### 📋 当前持仓")
        for code, pos in positions.items():
            name = pos.get('stock_name', '')
            shares = pos.get('shares', 0)
            avg_cost = pos.get('avg_cost', 0)
            current_price = pos.get('current_price', 0)
            gain = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
            lines.append(f"- {code} {name} {shares}股 成本{avg_cost:.2f} "
                         f"现价{current_price:.2f} ({gain:+.2f}%)")
    else:
        lines.append("### 📋 当前持仓")
        lines.append("空仓")

    lines.append("")
    lines.append("---")
    lines.append(f"复盘时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    content = "\n".join(lines)

    # 写入复盘
    result = api_post("/review", {
        "content": content,
        "tags": ["daily", "overnight"],
        "strategies": ["一夜持股法"]
    })

    if "error" in result:
        logger.error(f"复盘写入失败: {result['error']}")
        return 1

    logger.info(f"✅ 复盘写入完成 (id={result.get('id', '?')})")
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"🥚 每日复盘摘要 {today}")
    logger.info(f"总资产: {fmt(total_value)} | 盈亏: {fmt(total_profit)} ({profit_pct:+.2f}%)")
    if today_trades:
        logger.info(f"今日交易: {len(today_trades)} 笔")
    logger.info("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
