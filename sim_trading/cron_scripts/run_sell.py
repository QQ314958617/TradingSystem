#!/usr/bin/env python3
"""
次日早盘卖出 — 09:25 开始，每5分钟执行一次（至10:30）
根据止盈/止损条件判断是否卖出
"""
import sys
import os
import json
import logging
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.overnight_strategy import should_sell, bj_now, get_stock_detail, get_rsi

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger('run_sell')

API_BASE = "http://localhost/api"
HIGH_PRICE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'today_high.json'
)


def api_get(path):
    req = urllib.request.Request(f"{API_BASE}{path}",
                                  headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def api_post(path, data):
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(f"{API_BASE}{path}", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def load_high_prices():
    """加载今日最高价记录"""
    if not os.path.exists(HIGH_PRICE_FILE):
        return {}
    with open(HIGH_PRICE_FILE, 'r') as f:
        return json.load(f)


def save_high_price(code, high_price):
    """更新今日最高价"""
    data = load_high_prices()
    today = bj_now().strftime('%Y-%m-%d')
    if 'date' not in data or data['date'] != today:
        data = {'date': today, 'prices': {}}
    data['prices'][code] = max(data['prices'].get(code, 0), high_price)
    os.makedirs(os.path.dirname(HIGH_PRICE_FILE), exist_ok=True)
    with open(HIGH_PRICE_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False)


def main():
    now = bj_now()
    logger.info(f"[卖出] 开始 {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # 获取持仓（只看策略1-一夜持股法）
    portfolio = api_get("/portfolio?strategy_id=1")
    positions = portfolio.get('positions', {})

    if not positions:
        logger.info("无持仓，跳过")
        return 0

    # 加载今日最高价记录
    high_data = load_high_prices()

    for code, pos in positions.items():
        name = pos.get('stock_name', '')
        shares = pos['shares']
        avg_cost = pos['avg_cost']

        logger.info(f"检查持仓: {code} {name} {shares}股 成本{avg_cost:.2f}")

        # 获取实时行情
        detail = get_stock_detail(code)
        current_price = detail.get('price', 0)
        if current_price <= 0:
            logger.warning(f"获取 {code} 实时价格失败，跳过")
            continue

        # 更新今日最高价
        highest_today = max(high_data.get('prices', {}).get(code, current_price), current_price)
        save_high_price(code, highest_today)

        # 额外数据：RSI、量比、分时均价
        rsi = get_rsi(code)
        vol_ratio = detail.get('volume_ratio', 1.0)
        avg_price = detail.get('avg_price', 0)

        pos['current_rsi'] = rsi
        pos['current_vol_ratio'] = vol_ratio
        pos['current_avg_price'] = avg_price

        # 判断是否卖出
        decision = should_sell(pos, current_price, highest_today)

        gain_pct = (current_price - avg_cost) / avg_cost * 100
        logger.info(f"  当前价{current_price:.2f} 涨幅{gain_pct:+.2f}% "
                    f"今日最高{highest_today:.2f} RSI{rsi:.1f}")
        logger.info(f"  判断: {decision['reason']} | 卖出={decision['sell']}")

        if decision['sell']:
            reason = decision['reason']
            logger.info(f"执行卖出: {code} {name} {shares}股 @{current_price:.2f}")
            result = api_post("/trade", {
                "action": "sell",
                "stock_code": code,
                "shares": shares,
                "reason": f"一夜持股法卖出 | {reason}",
                "strategy_id": 1
            })

            if result.get('success'):
                trade = result.get('trade', {})
                profit = trade.get('profit', 0)
                logger.info(f"✅ 卖出成功: {code} {shares}股 @{trade.get('price', current_price):.2f}")
                logger.info(f"   盈亏: {profit:+.0f}元 ({gain_pct:+.2f}%)")
                logger.info(f"   交易ID: {result.get('trade_id')}")
            else:
                logger.error(f"❌ 卖出失败: {result}")
                return 1
        else:
            logger.info(f"  继续持有")

    return 0


if __name__ == '__main__':
    sys.exit(main())
