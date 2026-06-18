#!/usr/bin/env python3
"""
一夜持股法早盘卖出检查
检查持仓是否符合卖出条件：
1. 冲高5-8%止盈
2. 回落-2%
3. RSI>70
4. 放量滞涨
5. 跌破分时均价线
"""

import requests
import json
from datetime import datetime

# 一夜持股法持仓 (strategy_id=1)
OVERNIGHT_POSITIONS = [
    {"code": "002649", "name": "博彦科技", "shares": 300, "cost": 9.45},
    {"code": "300036", "name": "超图软件", "shares": 200, "cost": 13.24},
    {"code": "688168", "name": "安博通", "shares": 100, "cost": 53.27},
    {"code": "688658", "name": "悦康药业", "shares": 700, "cost": 13.66},
]

def get_prefix(code):
    """股票代码前缀"""
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    else:
        return "sz"

def get_realtime_quotes(codes):
    """获取实时行情"""
    prefixed = [f"{get_prefix(c)}{c}" for c in codes]
    url = f"https://qt.gtimg.cn/q={','.join(prefixed)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    data = resp.read().decode("gbk") if hasattr(resp, 'read') else resp.text
    
    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "volume": float(vals[36]) if vals[36] else 0,  # 成交量(手)
            "amount": float(vals[37]) if vals[37] else 0,  # 成交额(万)
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "vol_ratio": float(vals[49]) if vals[49] else 0,
        }
    return result

def get_kline_data(code, days=14):
    """获取K线数据用于计算RSI"""
    # 使用mootdx或腾讯K线接口
    import urllib.request
    
    prefix = get_prefix(code)
    # 腾讯日K线接口
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,{days},qfq"
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode("utf-8"))
    
    klines = []
    stock_data = data.get("data", {}).get(f"{prefix}{code}", {})
    day_data = stock_data.get("day") or stock_data.get("qfqday", [])
    
    for k in day_data:
        klines.append({
            "date": k[0],
            "open": float(k[1]),
            "close": float(k[2]),
            "high": float(k[3]),
            "low": float(k[4]),
            "volume": float(k[5]) if len(k) > 5 else 0,
        })
    return klines

def calc_rsi(closes, period=14):
    """计算RSI"""
    if len(closes) < period + 1:
        return None
    
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def check_selling_conditions(pos, quote, rsi):
    """检查卖出条件"""
    code = pos["code"]
    name = pos["name"]
    cost = pos["cost"]
    current = quote["price"]
    
    if current == 0 or cost == 0:
        return False, "数据异常"
    
    profit_pct = (current - cost) / cost * 100
    
    # 条件1: 冲高5-8%止盈
    if 5 <= profit_pct <= 8:
        return True, f"冲高止盈 +{profit_pct:.2f}%"
    
    # 条件2: 回落-2%
    if profit_pct <= -2:
        return True, f"回落止损 {profit_pct:.2f}%"
    
    # 条件3: RSI>70
    if rsi and rsi > 70:
        return True, f"RSI超买 {rsi}"
    
    # 条件4: 放量滞涨 (量比>2 且 涨幅<1%)
    if quote["vol_ratio"] > 2 and abs(profit_pct) < 1:
        return True, f"放量滞涨 量比{quote['vol_ratio']}"
    
    # 条件5: 跌破分时均价线 (简化：当前价低于开盘价)
    if current < quote["open"] and profit_pct < 0:
        return True, f"跌破均价线 开盘{quote['open']} 现价{current}"
    
    return False, f"未触发 盈亏{profit_pct:.2f}% RSI={rsi or 'N/A'}"

def main():
    print("=" * 60)
    print(f"🌅 一夜持股法早盘卖出检查 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    codes = [p["code"] for p in OVERNIGHT_POSITIONS]
    
    # 1. 获取实时行情
    print("\n📊 获取实时行情...")
    quotes = get_realtime_quotes(codes)
    
    # 2. 计算RSI
    print("📈 计算RSI指标...")
    rsi_data = {}
    for code in codes:
        try:
            klines = get_kline_data(code, 20)
            if klines:
                closes = [k["close"] for k in klines]
                rsi = calc_rsi(closes, 14)
                rsi_data[code] = rsi
                print(f"  {code}: RSI={rsi}")
        except Exception as e:
            print(f"  {code}: RSI计算失败 - {e}")
            rsi_data[code] = None
    
    # 3. 检查卖出条件
    print("\n🔍 检查卖出条件...")
    to_sell = []
    
    for pos in OVERNIGHT_POSITIONS:
        code = pos["code"]
        quote = quotes.get(code, {})
        rsi = rsi_data.get(code)
        
        if not quote:
            print(f"  ❌ {pos['name']}({code}): 无行情数据")
            continue
        
        should_sell, reason = check_selling_conditions(pos, quote, rsi)
        
        profit_pct = (quote["price"] - pos["cost"]) / pos["cost"] * 100
        
        if should_sell:
            print(f"  🔴 {pos['name']}({code}): 卖出 - {reason}")
            print(f"     成本{pos['cost']} 现价{quote['price']} 盈亏{profit_pct:.2f}%")
            to_sell.append({
                "code": code,
                "name": pos["name"],
                "shares": pos["shares"],
                "reason": reason,
                "price": quote["price"],
                "profit_pct": profit_pct
            })
        else:
            print(f"  🟢 {pos['name']}({code}): 持有 - {reason}")
            print(f"     成本{pos['cost']} 现价{quote['price']} 盈亏{profit_pct:.2f}%")
    
    # 4. 输出待卖出列表
    print("\n" + "=" * 60)
    if to_sell:
        print(f"📋 待卖出股票 ({len(to_sell)}只):")
        for s in to_sell:
            print(f"  • {s['name']}({s['code']}): {s['shares']}股 - {s['reason']}")
        
        # 生成卖出JSON
        sell_commands = []
        for s in to_sell:
            sell_commands.append({
                "action": "sell",
                "stock_code": s["code"],
                "shares": s["shares"],
                "reason": f"一夜持股法-{s['reason']}"
            })
        
        print("\n📝 卖出命令:")
        print(json.dumps(sell_commands, ensure_ascii=False, indent=2))
    else:
        print("✅ 无股票需要卖出，继续持有")
    
    print("\n" + "=" * 60)
    return to_sell

if __name__ == "__main__":
    to_sell = main()
