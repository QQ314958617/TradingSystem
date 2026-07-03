#!/usr/bin/env python3
"""
尾盘买入执行 — 14:50 执行
读取扫描缓存，选最优候选股，满仓买入
"""
import sys
import os
import json
import logging
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.overnight_strategy import (
    select_best_candidate, calc_position_size, bj_now, get_stock_detail
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger('run_buy')

API_BASE = "http://localhost/api"
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'scan_candidates.json')
BUY_LOCK_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'data', 'today_bought.json')


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


def load_scan_result():
    if not os.path.exists(CACHE_FILE):
        logger.warning("扫描缓存不存在，请先运行 run_scan.py")
        return None
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 检查缓存是否是今天的
    scan_date = data.get('date', '')
    today = bj_now().strftime('%Y-%m-%d')
    if scan_date != today:
        logger.warning(f"扫描缓存已过期 ({scan_date} != {today})")
        return None
    return data


def already_bought_today():
    """今日是否已经买入过"""
    if not os.path.exists(BUY_LOCK_FILE):
        return False
    with open(BUY_LOCK_FILE, 'r') as f:
        data = json.load(f)
    today = bj_now().strftime('%Y-%m-%d')
    return data.get('date') == today


def save_buy_lock(stock_code, stock_name, shares, price):
    today = bj_now().strftime('%Y-%m-%d')
    with open(BUY_LOCK_FILE, 'w') as f:
        json.dump({
            'date': today,
            'stock_code': stock_code,
            'stock_name': stock_name,
            'shares': shares,
            'price': price,
            'buy_time': bj_now().isoformat()
        }, f, ensure_ascii=False)


def main():
    now = bj_now()
    logger.info(f"[买入] 开始 {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # 防重复买入
    if already_bought_today():
        logger.info("今日已完成买入，跳过")
        return 0

    # 读取扫描结果
    scan = load_scan_result()
    if not scan or not scan.get('candidates'):
        logger.info("无候选股，今日空仓")
        return 0

    # 选最优候选
    best = select_best_candidate(scan['candidates'])
    if not best:
        logger.info("候选选择失败")
        return 0

    code = best['code']
    name = best['name']
    score = best.get('score', 0)

    logger.info(f"选定候选: {code} {name} score={score}")

    # 获取账户信息
    portfolio = api_get("/portfolio")
    cash = portfolio.get('cash', 0)
    positions = portfolio.get('positions', {})

    if code in positions:
        logger.info(f"已持有 {code}，跳过")
        return 0

    if cash < 1000:
        logger.info(f"现金不足 ({cash:.0f}元)，跳过")
        return 0

    # 获取最新价格（实时）
    detail = get_stock_detail(code)
    price = detail.get('price', 0)
    if price <= 0:
        logger.error(f"获取 {code} 实时价格失败")
        return 1

    # 计算满仓股数
    pos = calc_position_size(cash, price)
    shares = pos['shares']
    if shares <= 0:
        logger.error(f"资金不足以买入100股: cash={cash} price={price}")
        return 1

    # 构造买入理由
    cond = best.get('condition_details', {})
    reason = (
        f"一夜持股法 | score={score:.1f} | "
        f"涨幅{best['change_pct']:.2f}% | "
        f"RSI{best.get('rsi',0):.1f} | "
        f"量比{best.get('vol_ratio_5d',0):.1f}x | "
        f"换手{best['turnover']:.1f}% | "
        f"流通{best['circulate_mv']:.0f}亿"
    )

    logger.info(f"执行买入: {code} {name} {shares}股 @{price} 总额{pos['amount']:.0f}元")
    logger.info(f"理由: {reason}")

    # 执行买入
    result = api_post("/trade", {
        "action": "buy",
        "stock_code": code,
        "shares": shares,
        "reason": reason,
        "strategy_id": 1
    })

    if result.get('success'):
        trade = result.get('trade', {})
        logger.info(f"✅ 买入成功: {code} {shares}股 @{trade.get('price', price):.2f}")
        logger.info(f"   交易ID: {result.get('trade_id')}")
        logger.info(f"   剩余现金: {result.get('portfolio', {}).get('cash', 0):.0f}元")
        save_buy_lock(code, name, shares, price)
    else:
        logger.error(f"❌ 买入失败: {result}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
