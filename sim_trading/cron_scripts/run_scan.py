#!/usr/bin/env python3
"""
尾盘选股扫描 — 14:45 执行
扫描满足一夜持股法7条件的候选股，结果写入缓存文件
"""
import sys
import os
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.overnight_strategy import scan_candidates, bj_now

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger('run_scan')

CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'scan_candidates.json')


def main():
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)

    now = bj_now()
    logger.info(f"[扫描] 开始尾盘扫描 {now.strftime('%Y-%m-%d %H:%M:%S')}")

    candidates = scan_candidates()

    result = {
        'scan_time': now.isoformat(),
        'date': now.strftime('%Y-%m-%d'),
        'count': len(candidates),
        'candidates': candidates
    }

    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if candidates:
        top = candidates[0]
        logger.info(f"✅ 扫描完成: {len(candidates)} 只候选")
        logger.info(f"   最优: {top['code']} {top['name']} "
                    f"涨幅{top['change_pct']:.2f}% "
                    f"RSI{top.get('rsi', 0):.1f} "
                    f"score={top['score']}")
        for c in candidates[:5]:
            logger.info(f"   - {c['code']} {c['name']} "
                        f"涨{c['change_pct']:.2f}% "
                        f"换手{c['turnover']:.1f}% "
                        f"流通{c['circulate_mv']:.0f}亿 "
                        f"RSI{c.get('rsi',0):.0f} "
                        f"量比{c.get('vol_ratio_5d',0):.1f}x "
                        f"score={c['score']}")
    else:
        logger.info("⚠️  扫描结果：无符合条件候选股，今日空仓")

    return 0


if __name__ == '__main__':
    sys.exit(main())
