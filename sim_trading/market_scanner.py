"""
全市场扫盘器 v1.1 — 纯腾讯API版
=================================
架构：
1. 代码列表：硬编码生成（替代已死的akshare stock_info_a_code_name）
2. 腾讯qt.gtimg.cn批量查询 → 实时价/涨幅/换手率/成交量
3. 多条件过滤
4. RSI从腾讯K线获取
"""
import pandas as pd
import numpy as np
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


# ═══════════════════════════════════════
# 股票列表（硬编码生成）
# ═══════════════════════════════════════

def get_all_code_list() -> list:
    """生成全A股代码列表（替代akshare stock_info_a_code_name）"""
    codes = []
    for prefix in ['sh600', 'sh601', 'sh603', 'sh605']:
        codes.extend([f'{prefix}{i:0>3d}' for i in range(1000)])
    codes.extend([f'sh688{i:0>3d}' for i in range(600)])
    for prefix in ['sz000', 'sz001']:
        codes.extend([f'{prefix}{i:0>3d}' for i in range(1000)])
    for prefix in ['sz002', 'sz003']:
        codes.extend([f'{prefix}{i:0>3d}' for i in range(1000)])
    for prefix in ['sz300', 'sz301']:
        codes.extend([f'{prefix}{i:0>3d}' for i in range(1000)])
    return codes  # ~7600只


# ═══════════════════════════════════════
# 腾讯批量行情（并发）
# ═══════════════════════════════════════

def batch_tencent_quotes(prefixed_codes: list) -> dict:
    """批量查询腾讯行情"""
    result = {}
    try:
        url = f"https://qt.gtimg.cn/q={','.join(prefixed_codes)}"
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
        r = requests.get(url, headers=headers, timeout=20)
        for line in r.text.strip().split(';'):
            if '="' not in line:
                continue
            try:
                fields = line.split('="')[1].strip('"').split('~')
                if len(fields) < 46:
                    continue
                code_raw = fields[2]
                price = float(fields[3]) if fields[3] not in ('', '-') else 0
                if price == 0 or code_raw == fields[1]:
                    continue
                result[code_raw] = {
                    'name': fields[1], 'code': code_raw,
                    'price': price,
                    'change_pct': float(fields[32]) if len(fields) > 32 and fields[32] not in ('', '-') else 0,
                    'turnover': float(fields[38]) if len(fields) > 38 and fields[38] not in ('', '-') else 0,
                    'volume_ratio': float(fields[49]) if len(fields) > 49 and fields[49] not in ('', '-') else 1.0,
                    'amount': float(fields[37]) if len(fields) > 37 and fields[37] not in ('', '-') else 0,
                    'circulate_mv': float(fields[44]) if len(fields) > 44 and fields[44] not in ('', '-') else 0,
                }
            except (IndexError, ValueError):
                continue
    except Exception:
        pass
    return result


def scan_market() -> pd.DataFrame:
    """全市场扫描（纯腾讯，并发）"""
    codes = get_all_code_list()
    total = len(codes)
    
    all_quotes = {}
    batches = [codes[i:i+500] for i in range(0, total, 500)]
    
    def _fetch(batch):
        return batch_tencent_quotes(batch)
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_fetch, b) for b in batches]
        for f in as_completed(futures):
            all_quotes.update(f.result())
    
    # 组装DataFrame
    rows = [q for q in all_quotes.values() if q['price'] > 0]
    return pd.DataFrame(rows)





def get_market_overview() -> dict:
    """市场概况"""
    df = scan_market()
    if df.empty or 'change_pct' not in df.columns:
        return {'error': '扫描失败'}
    
    return {
        'total_stocks': len(df),
        'up_stocks': int((df['change_pct'] > 0).sum()),
        'down_stocks': int((df['change_pct'] < 0).sum()),
        'flat_stocks': int((df['change_pct'] == 0).sum()),
        'median_change': float(df['change_pct'].median()),
        'limit_up': int((df['change_pct'] >= 9.8).sum()),
        'limit_down': int((df['change_pct'] <= -9.8).sum()),
        'top_gainers': df.nlargest(5, 'change_pct')[['code', 'name', 'change_pct']].to_dict('records'),
        'top_losers': df.nsmallest(5, 'change_pct')[['code', 'name', 'change_pct']].to_dict('records'),
    }
