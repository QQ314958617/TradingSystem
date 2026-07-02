"""
信号数据服务 — 统一封装a-stock-data技能包的数据源
=================================================
集成：同花顺热点归因、东财龙虎榜、东财资金流(分钟级+日级)、行业板块排名
供复盘/策略引擎调用

数据源验证状态（2026-05-28）：
  ✅ 同花顺热点归因 (ths_hot_reason)
  ✅ 东财push2资金流分钟级 (eastmoney_fund_flow_minute)
  ✅ 东财push2资金流120日 (stock_fund_flow_120d)
  ✅ 东财龙虎榜 (dragon_tiger_board / daily_dragon_tiger)
  ✅ 东财行业板块排名 (industry_comparison)
"""
import requests
import logging
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


# ═══════════════════════════════════════
# 东财数据中心统一查询 helper
# ═══════════════════════════════════════

def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                         filter_str: str = "", page_size: int = 50,
                         sort_columns: str = "", sort_types: str = "-1") -> list:
    """东财数据中心统一查询 — 龙虎榜/解禁/融资融券/大宗交易/股东户数 共用"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    try:
        r = requests.get(DATACENTER_URL, params=params,
                         headers={"User-Agent": UA}, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
    except Exception as e:
        logger.warning(f"eastmoney_datacenter({report_name}) 失败: {e}")
    return []


# ═══════════════════════════════════════
# 同花顺热点归因（独家：告诉你"为什么涨"）
# ═══════════════════════════════════════

def ths_hot_reason(trade_date: str = None) -> list:
    """
    同花顺当日强势股归因。
    trade_date: 'YYYY-MM-DD' 格式，None=今天
    返回: [{'code', 'name', 'reason', 'change_pct', 'turnover', 'main_net'}, ...]
    """
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    url = (
        f"http://zx.10jqka.com.cn/event/api/getharden/"
        f"date/{trade_date}/orderby/date/orderway/desc/charset/GBK/"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get("errocode", 0) != 0:
            logger.warning(f"同花顺热点错误: {data.get('errormsg', '')}")
            return []

        rows = data.get("data") or []
        result = []
        for row in rows:
            result.append({
                'code': str(row.get('code', '')),
                'name': str(row.get('name', '')),
                'reason': str(row.get('reason', '')),  # 核心：题材归因tags
                'change_pct': float(row.get('zhangfu', 0) or 0),
                'turnover': float(row.get('huanshou', 0) or 0),
                'main_net': float(row.get('ddejingliang', 0) or 0),  # 大单净量
            })
        return result
    except Exception as e:
        logger.warning(f"同花顺热点获取失败: {e}")
        return []


def get_hot_themes(trade_date: str = None, top_n: int = 10) -> list:
    """
    提取当日TOP N热门题材（从热点归因中统计词频）
    返回: [{'theme': '算力租赁', 'count': 12, 'stocks': ['xxx', ...]}, ...]
    """
    from collections import Counter
    hot_stocks = ths_hot_reason(trade_date)
    if not hot_stocks:
        return []

    theme_stocks = {}  # theme -> [codes]
    for s in hot_stocks:
        tags = [t.strip() for t in str(s['reason']).split('+') if t.strip()]
        for tag in tags:
            if tag not in theme_stocks:
                theme_stocks[tag] = []
            theme_stocks[tag].append(s['code'])

    # 按出现次数排序
    result = []
    for theme, stocks in sorted(theme_stocks.items(), key=lambda x: len(x[1]), reverse=True)[:top_n]:
        result.append({
            'theme': theme,
            'count': len(stocks),
            'stocks': stocks[:5],  # 只保留前5只代表股
        })
    return result


def is_stock_in_hot_theme(code: str, trade_date: str = None) -> dict:
    """
    检查个股是否在当日热点题材中
    返回: {'in_hot': True/False, 'themes': ['题材1', '题材2'], 'reason': '完整归因'}
    """
    hot_stocks = ths_hot_reason(trade_date)
    for s in hot_stocks:
        if s['code'] == code:
            themes = [t.strip() for t in str(s['reason']).split('+') if t.strip()]
            return {'in_hot': True, 'themes': themes, 'reason': s['reason']}
    return {'in_hot': False, 'themes': [], 'reason': ''}


# ═══════════════════════════════════════
# 东财资金流（分钟级 + 日级）
# ═══════════════════════════════════════

def fund_flow_minute(code: str) -> list:
    """
    个股资金流向（分钟级，当日盘中）。
    返回: [{'time', 'main_net', 'small_net', 'mid_net', 'large_net', 'super_net'}, ...]
    单位: 元
    """
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid, "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        rows = []
        for line in d.get("data", {}).get("klines", []):
            parts = line.split(",")
            if len(parts) >= 6:
                rows.append({
                    "time": parts[0],
                    "main_net": float(parts[1]),
                    "small_net": float(parts[2]),
                    "mid_net": float(parts[3]),
                    "large_net": float(parts[4]),
                    "super_net": float(parts[5]),
                })
        return rows
    except Exception as e:
        logger.warning(f"push2资金流({code})失败: {e}")
        return []


def fund_flow_summary(code: str) -> dict:
    """
    个股当日资金流汇总（主力净流入方向+金额）
    返回: {'main_net_wan': 万元, 'direction': 'inflow'/'outflow', 'score': 0-20}
    """
    data = fund_flow_minute(code)
    if not data:
        return {'main_net_wan': 0, 'direction': 'unknown', 'score': 0}

    # 累计主力净流入
    total_main = sum(r['main_net'] for r in data)
    total_wan = total_main / 10000

    # 评分：主力净流入越多分越高
    if total_wan > 5000:
        score = 20
    elif total_wan > 2000:
        score = 16
    elif total_wan > 500:
        score = 12
    elif total_wan > 0:
        score = 8
    elif total_wan > -1000:
        score = 4
    else:
        score = 0

    direction = 'inflow' if total_wan > 0 else 'outflow'
    return {'main_net_wan': round(total_wan, 1), 'direction': direction, 'score': score}


def fund_flow_120d(code: str) -> list:
    """
    个股资金流（日级，最近120个交易日）。
    返回: [{'date', 'main_net', 'small_net', 'mid_net', 'large_net', 'super_net'}, ...]
    单位: 元
    """
    market_code = 1 if code.startswith("6") else 0
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": f"{market_code}.{code}",
        "klt": "101",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
        "lmt": "120",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        rows = []
        for line in d.get("data", {}).get("klines", []):
            parts = line.split(",")
            if len(parts) >= 6:
                rows.append({
                    "date": parts[0],
                    "main_net": float(parts[1]),
                    "small_net": float(parts[2]),
                    "mid_net": float(parts[3]),
                    "large_net": float(parts[4]),
                    "super_net": float(parts[5]),
                })
        return rows
    except Exception as e:
        logger.warning(f"push2his资金流120d({code})失败: {e}")
        return []


def fund_flow_trend(code: str, days: int = 5) -> dict:
    """
    近N日资金流趋势判断
    返回: {'net_5d_wan': 万元, 'consecutive_inflow': 连续流入天数, 'trend': 'strong'/'weak'/'neutral'}
    """
    data = fund_flow_120d(code)
    if not data or len(data) < days:
        return {'net_5d_wan': 0, 'consecutive_inflow': 0, 'trend': 'unknown'}

    recent = data[-days:]
    net_total = sum(r['main_net'] for r in recent) / 10000

    # 连续流入天数（从最近一天往前数）
    consecutive = 0
    for r in reversed(data):
        if r['main_net'] > 0:
            consecutive += 1
        else:
            break

    if net_total > 3000 and consecutive >= 3:
        trend = 'strong'
    elif net_total > 0:
        trend = 'neutral'
    else:
        trend = 'weak'

    return {'net_5d_wan': round(net_total, 1), 'consecutive_inflow': consecutive, 'trend': trend}


# ═══════════════════════════════════════
# 龙虎榜
# ═══════════════════════════════════════

def dragon_tiger_check(code: str, trade_date: str = None, look_back: int = 30) -> dict:
    """
    检查个股近期龙虎榜情况
    返回: {'on_board': True/False, 'records': [...], 'institution_net_wan': 万元, 'score': 0-15}
    """
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    start = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)
    start_str = start.strftime("%Y-%m-%d")

    # 上榜记录
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_str}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
        page_size=20,
        sort_columns="TRADE_DATE", sort_types="-1",
    )

    if not data:
        return {'on_board': False, 'records': [], 'institution_net_wan': 0, 'score': 0}

    records = []
    for row in data:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
        })

    # 查最近一次的买入席位，看有没有机构
    latest_date = records[0]["date"]
    buy_data = eastmoney_datacenter(
        "RPT_BILLBOARD_DAILYDETAILSBUY",
        filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
        page_size=10,
        sort_columns="BUY", sort_types="-1",
    )

    institution_net = 0
    for row in buy_data:
        if str(row.get("OPERATEDEPT_CODE", "")) == "0":  # 机构专用席位
            institution_net += (row.get("BUY") or 0) - (row.get("SELL") or 0)
    institution_net_wan = round(institution_net / 10000, 1)

    # 评分
    score = 0
    if len(records) >= 3:
        score += 5  # 频繁上榜
    elif len(records) >= 1:
        score += 3
    if institution_net_wan > 1000:
        score += 10  # 机构大买
    elif institution_net_wan > 0:
        score += 5   # 机构小买
    # 净买入为正加分
    total_net = sum(r['net_buy_wan'] for r in records)
    if total_net > 5000:
        score += 5

    return {
        'on_board': True,
        'records': records[:5],
        'institution_net_wan': institution_net_wan,
        'total_net_wan': round(total_net, 1),
        'score': min(score, 15),
    }


def daily_dragon_tiger_top(trade_date: str = None, top_n: int = 20) -> list:
    """
    全市场龙虎榜TOP N（按净买入排序）
    返回: [{'code', 'name', 'reason', 'net_buy_wan', 'change_pct'}, ...]
    """
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
        page_size=100,
        sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )

    stocks = []
    for row in data[:top_n]:
        stocks.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "reason": row.get("EXPLANATION", ""),
            "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
        })
    return stocks


# ═══════════════════════════════════════
# 行业板块排名
# ═══════════════════════════════════════

def industry_ranking(top_n: int = 10) -> dict:
    """
    全行业涨跌幅排名（东财行业板块）
    返回: {'top': [...], 'bottom': [...], 'total': int}
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "100", "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        if not items:
            return {"top": [], "bottom": [], "total": 0}

        rows = []
        for i, item in enumerate(items):
            rows.append({
                "rank": i + 1,
                "name": item.get("f14", ""),
                "change_pct": item.get("f3", 0),
                "up_count": item.get("f104", 0),
                "down_count": item.get("f105", 0),
                "leader": item.get("f140", ""),
                "leader_change": item.get("f136", 0),
            })

        return {"top": rows[:top_n], "bottom": rows[-top_n:], "total": len(rows)}
    except Exception as e:
        logger.warning(f"行业板块排名获取失败: {e}")
        return {"top": [], "bottom": [], "total": 0}


def is_industry_hot(industry_name: str) -> dict:
    """
    判断某行业是否在当日热门板块中
    返回: {'is_hot': True/False, 'rank': 排名, 'change_pct': 涨幅}
    """
    data = industry_ranking(top_n=100)
    for item in data.get('top', []) + data.get('bottom', []):
        if industry_name in item.get('name', ''):
            is_hot = item['rank'] <= 10
            return {'is_hot': is_hot, 'rank': item['rank'], 'change_pct': item['change_pct']}
    return {'is_hot': False, 'rank': 0, 'change_pct': 0}
