#!/usr/bin/env python3
"""
一夜持股法选股系统 v3.0 (AKShare重写版)
=======================================
策略：尾盘14:30-14:55选股，次日早盘卖出
核心：宁可错过，不可做错

v3.0 重大升级（基于AKShare接口测试）:
- 数据源: stock_zt_pool_strong_em (今日强势股池) ✅
- 补充验证: stock_rank_xstp_ths (向上突破) ✅
- 实时行情: 腾讯 qt.gtimg.cn ✅
- 行业数据: stock_board_industry_summary_ths ✅
- 板块数据: stock_board_concept_name_ths ✅
- 全市场筛选: stock_zh_a_spot_em ❌ (IP被封)
- 行业涨跌: stock_board_industry_name_em ❌ (IP被封)

接口状态（2026-04-16验证）:
  ✅ stock_zt_pool_strong_em      今日强势股(涨停/涨幅股)
  ✅ stock_zt_pool_previous_em   昨日涨停股池
  ✅ stock_individual_info_em      个股基本信息
  ✅ stock_board_industry_summary_ths  THS行业涨跌排行
  ✅ stock_rank_xstp_ths          向上突破选股
  ✅ stock_zh_index_daily          指数历史K线
  ✅ qt.gtimg.cn (腾讯)           实时价格/换手率
  ❌ stock_zh_a_spot_em           全市场(东方财富IP被封)
  ❌ stock_board_industry_name_em  行业板块(东方财富IP被封)
  ❌ stock_board_concept_spot_em  概念板块(东方财富IP被封)
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import json
import sys
import os
import requests
import time
import warnings
warnings.filterwarnings('ignore')

# 信号数据服务（题材归因+资金流+龙虎榜）
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from services.signal import (
        is_stock_in_hot_theme, fund_flow_summary,
        dragon_tiger_check, get_hot_themes
    )
    SIGNAL_AVAILABLE = True
except ImportError:
    SIGNAL_AVAILABLE = False

# ========== 策略参数 v3.0 ==========
class Config:
    # 涨幅区间（%）：3%-5%
    RISE_MIN = 3.0
    RISE_MAX = 5.0
    # 换手率区间（%）：3%-10%
    TURNOVER_MIN = 3.0
    TURNOVER_MAX = 10.0
    # 流通市值（亿元）：50-200亿
    MARKET_CAP_MIN = 50
    MARKET_CAP_MAX = 200
    # 选股时间窗口（尾盘）：14:50-14:55
    SCREEN_START = "14:50"
    SCREEN_END = "14:55"
    # 最大持仓数量
    MAX_STOCKS = 3


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def get_tencent_quotes(codes):
    """腾讯API批量获取实时行情"""
    if not codes:
        return {}
    # 构造腾讯行情代码
    code_str = ','.join([
        f"sh{c}" if c.startswith(('6', '5')) else f"sz{c}" 
        for c in codes
    ])
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://gu.qq.com/'
        }
        r = requests.get(f"https://qt.gtimg.cn/q={code_str}", 
                        headers=headers, timeout=8)
        result = {}
        for line in r.text.strip().split('\n'):
            if '=' not in line:
                continue
            key_part = line.split('=')[0].replace('v_', '')
            if '="' not in line:
                continue
            fields = line.split('="')[1].strip('"').split('~')
            if len(fields) < 40:
                continue
            code = key_part.upper().replace('SH', '').replace('SZ', '')
            try:
                result[code] = {
                    'name':    fields[1],
                    'price':   float(fields[3])  if fields[3]  != '-' else 0,
                    'close':   float(fields[4])  if fields[4]  != '-' else 0,
                    'open':    float(fields[5])  if fields[5]  != '-' else 0,
                    'high':    float(fields[33]) if fields[33] != '-' else 0,
                    'low':     float(fields[34]) if fields[34] != '-' else 0,
                    'amount':  float(fields[37]) if fields[37] != '-' else 0,  # 成交额(元)
                    'turnover':float(fields[38]) if fields[38] != '-' else 0,  # 换手率%
                    'change_pct': float(fields[32]) if fields[32] != '-' else 0,  # 涨跌幅%
                }
            except (ValueError, IndexError):
                continue
        return result
    except Exception as e:
        log(f"腾讯API错误: {e}")
        return {}


def get_index_realtime():
    """获取大盘指数实时数据（上证指数）"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
        r = requests.get("https://qt.gtimg.cn/q=sh000001", headers=headers, timeout=5)
        fields = r.text.split('="')[1].strip('"').split('~')
        return {
            'name':       fields[1],
            'price':      float(fields[3])  if fields[3]  != '-' else 0,
            'change_pct': float(fields[32]) if fields[32] != '-' else 0,
        }
    except:
        return None


def screen_overnight_v3():
    """
    一夜持股法选股主函数 v3.0
    
    选股逻辑：
    1. 从强势股池获取今日所有涨幅>3%的股票（来源: stock_zt_pool_strong_em）
    2. 筛选涨幅3-5%（排除涨停股）
    3. 换手率3%-10%
    4. 流通市值50-200亿
    5. 腾讯API实时价格二次确认
    6. 结合行业涨跌（THS）判断板块强度
    
    返回: 候选股票列表
    """
    today_str = date.today().strftime("%Y%m%d")
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    
    log(f"🔍 一夜持股法v3.0选股开始... 时间: {current_time} 日期: {today_str}")
    
    # Step 0: 大盘状态
    index_data = get_index_realtime()
    if index_data:
        direction = "▲" if index_data['change_pct'] > 0 else "▼"
        log(f"📈 大盘状态: {index_data['name']} {direction} {abs(index_data['change_pct']):.2f}%")
    else:
        log("⚠️ 大盘数据获取失败")
    
    # Step 1: 获取今日强势股池（核心数据源）
    log("🌐 Step1: 获取强势股池...")
    try:
        df_pool = ak.stock_zt_pool_strong_em(date=today_str)
        log(f"✅ 强势股总数: {len(df_pool)} 只")
    except Exception as e:
        log(f"❌ 强势股池获取失败: {e}")
        return [], None
    
    if df_pool.empty:
        log("❌ 强势股池为空")
        return [], index_data
    
    # Step 2: 行业涨跌排行（THS）
    log("🌐 Step2: 获取THS行业涨跌排行...")
    try:
        df_sector = ak.stock_board_industry_summary_ths()
        sector_dict = dict(zip(df_sector['板块'], df_sector['涨跌幅']))
        top_sectors = df_sector.head(5)['板块'].tolist()
        log(f"✅ 今日强势行业: {', '.join(top_sectors)}")
    except Exception as e:
        log(f"⚠️ 行业数据获取失败: {e}")
        sector_dict = {}
        top_sectors = []
    
    # Step 3: 筛选涨幅3%-5%
    df_candidates = df_pool[
        (df_pool['涨跌幅'] >= Config.RISE_MIN) & 
        (df_pool['涨跌幅'] <= Config.RISE_MAX)
    ].copy()
    log(f"✅ 涨幅{Config.RISE_MIN}-{Config.RISE_MAX}%区间: {len(df_candidates)} 只")
    
    if len(df_candidates) == 0:
        log("❌ 涨幅3-5%区间无股票")
        return [], index_data
    
    # Step 4: 换手率筛选（来自强势股池自带数据）
    df_candidates = df_candidates[
        (df_candidates['换手率'] >= Config.TURNOVER_MIN) &
        (df_candidates['换手率'] <= Config.TURNOVER_MAX)
    ].copy()
    log(f"✅ 换手率{Config.TURNOVER_MIN}-{Config.TURNOVER_MAX}%: {len(df_candidates)} 只")
    
    if len(df_candidates) == 0:
        log("❌ 换手率3-10%区间无股票")
        return [], index_data
    
    # Step 5: 流通市值筛选（强势股池自带字段，单位是元）
    df_candidates['流通市值_亿'] = df_candidates['流通市值'] / 1e8
    df_candidates = df_candidates[
        (df_candidates['流通市值_亿'] >= Config.MARKET_CAP_MIN) &
        (df_candidates['流通市值_亿'] <= Config.MARKET_CAP_MAX)
    ].copy()
    log(f"✅ 流通市值{Config.MARKET_CAP_MIN}-{Config.MARKET_CAP_MAX}亿: {len(df_candidates)} 只")
    
    if len(df_candidates) == 0:
        log("❌ 市值50-200亿无股票")
        return [], index_data
    
    # Step 6: 冷却期过滤——排除最近48小时内卖出过的股票
    log("⏳ Step6: 冷却期过滤（排除48h内卖出股票）...")
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        import database as db
        recently_sold = db.get_recently_sold_stocks(hours=48)
        sold_codes = set(r['stock_code'] for r in recently_sold)
        if sold_codes:
            log(f"🔇 最近48h内卖出: {', '.join(sold_codes)}")
            df_candidates = df_candidates[~df_candidates['代码'].isin(sold_codes)].copy()
            log(f"✅ 冷却过滤后剩余: {len(df_candidates)} 只")
            if len(df_candidates) == 0:
                log("❌ 所有候选股均在冷却期")
                return [], index_data
        else:
            log("✅ 无最近卖出记录，无需冷却过滤")
    except Exception as e:
        log(f"⚠️ 冷却期过滤失败(非致命): {e}")
    
    # Step 7: 腾讯实时价格（仅展示，不过滤）
    codes = df_candidates['代码'].tolist()
    quotes = get_tencent_quotes(codes)
    
    # Step 8: 信号层增强（题材归因+资金流+龙虎榜）
    log("🌐 Step8: 信号层数据增强...")
    hot_themes = []
    if SIGNAL_AVAILABLE:
        try:
            hot_themes = get_hot_themes(top_n=10)
            if hot_themes:
                log(f"✅ 今日热门题材: {', '.join([t['theme'] for t in hot_themes[:5]])}")
        except Exception as e:
            log(f"⚠️ 热门题材获取失败(非致命): {e}")
    
    # 用AKShare强势股池数据作为筛选主体（东方财富实时行情）
    # 腾讯API仅补充当前价等字段，不做二次过滤
    final_candidates = []
    for _, row in df_candidates.iterrows():
        code = str(row['代码'])
        qt = quotes.get(code, {})
        
        # 板块强度加成
        industry = str(row.get('所属行业', ''))
        sector_change = sector_dict.get(industry, 0)
        sector_bonus = 10 if sector_change > 2 else (5 if sector_change > 0 else 0)
        
        # 是否新高加分
        is_new_high = 1 if str(row.get('是否新高', '')) == '是' else 0
        
        # 综合评分（基础分）
        score = int(row['涨跌幅'] * 10)
        score += int(row['换手率'] / 2)
        score += sector_bonus
        score += (15 if is_new_high == 1 else 0)
        
        # === 信号层加分（新增） ===
        theme_info = {'in_hot': False, 'themes': [], 'reason': ''}
        fund_info = {'main_net_wan': 0, 'direction': 'unknown', 'score': 0}
        dragon_info = {'on_board': False, 'score': 0}
        
        if SIGNAL_AVAILABLE:
            try:
                # 题材归因加分（最高+15分）
                theme_info = is_stock_in_hot_theme(code)
                if theme_info['in_hot']:
                    theme_bonus = min(len(theme_info['themes']) * 5, 15)
                    score += theme_bonus
            except Exception:
                pass
            
            try:
                # 资金流加分（最高+20分）
                fund_info = fund_flow_summary(code)
                score += fund_info['score']
            except Exception:
                pass
            
            try:
                # 龙虎榜加分（最高+15分）
                dragon_info = dragon_tiger_check(code)
                score += dragon_info.get('score', 0)
            except Exception:
                pass
        
        final_candidates.append({
            'code':         code,
            'name':         row['名称'],
            '池涨幅':       round(row['涨跌幅'], 2),
            '池换手':       round(row['换手率'], 2),
            '流通市值_亿':  round(row['流通市值_亿'], 1),
            '行业':         industry,
            '板块涨幅':     sector_change,
            '当前价':       qt.get('price', row.get('最新价', 0)),
            '最高价':       qt.get('high', 0),
            'score':        score,
            'signal':       '★★★' if score >= 60 else ('★★' if score >= 45 else '★'),
            '是否新高':     '是' if is_new_high else '否',
            # 信号层数据
            '题材':         '+'.join(theme_info['themes'][:3]) if theme_info['in_hot'] else '',
            '主力净流入_万': fund_info['main_net_wan'],
            '资金方向':     fund_info['direction'],
            '龙虎榜':       '是' if dragon_info.get('on_board') else '否',
        })
    
    # 按评分排序
    final_candidates.sort(key=lambda x: x['score'], reverse=True)
    top_stocks = final_candidates[:Config.MAX_STOCKS]
    
    log(f"✅ 最终候选: {len(top_stocks)} 只")
    for s in top_stocks:
        log(f"  {s['signal']} {s['name']}({s['code']}) 涨幅{s['池涨幅']}% 换手{s['池换手']}% 市值{s['流通市值_亿']}亿 行业:{s['行业']} 评分:{s['score']}")
    
    return top_stocks, index_data


def format_report_v3(results, index_data=None):
    """格式化输出报告"""
    if not results:
        return (
            f"📊 **一夜持股法v3.0筛选结果**\n\n"
            f"❌ 今日暂无符合条件股票（空仓观望）\n\n"
            f"⏰ 选股时间窗口: 14:30-14:55\n"
            f"📋 筛选条件: 涨幅3-5% | 换手率3-10% | 市值50-200亿\n"
            f"🔗 数据来源: 东方财富强势股池 + 腾讯实时行情"
        )
    
    idx_info = ""
    if index_data and index_data.get('change_pct') is not None:
        d = "▲" if index_data['change_pct'] > 0 else "▼"
        idx_info = f"\n📈 大盘: {d} {abs(index_data['change_pct']):.2f}%"
    
    lines = [
        f"📊 **一夜持股法v3.0筛选结果**{idx_info}\n\n",
        f"📈 **候选股票** (共{len(results)}只)\n\n",
    ]
    
    for i, s in enumerate(results, 1):
        market = f"{s['流通市值_亿']:.0f}亿"
        industry = s['行业']
        sector_chg = s['板块涨幅']
        # 信号层标签
        signal_tags = []
        if s.get('题材'):
            signal_tags.append(f"🎯{s['题材']}")
        if s.get('资金方向') == 'inflow':
            signal_tags.append(f"💰主力流入{s['主力净流入_万']:.0f}万")
        elif s.get('资金方向') == 'outflow':
            signal_tags.append(f"💸主力流出{abs(s['主力净流入_万']):.0f}万")
        if s.get('龙虎榜') == '是':
            signal_tags.append("🐉龙虎榜")
        signal_line = f"   信号: {' | '.join(signal_tags)}\n" if signal_tags else ""
        
        lines.append(
            f"{i}. **{s['name']}({s['code']})** {s['signal']}\n"
            f"   强势股池涨幅: ▲{s['池涨幅']}% | "
            f"换手率: {s['池换手']}% | "
            f"市值: {market}\n"
            f"   行业: {industry}({sector_chg:+.2f}%) | "
            f"评分: {s['score']}分 | "
            f"是否新高: {s['是否新高']}\n"
            f"{signal_line}"
            f"   当前价(参考): ¥{s['当前价']}\n\n"
        )
    
    lines.extend([
        f"\n💡 **操作建议**:\n",
        f"- 选股时间: 14:30-14:55 尾盘买入\n",
        f"- 仓位分配: 策略资金¥100,000满仓一只\n",
        f"- 止损: -3% 无条件止损\n",
        f"- 止盈: 次日早盘(09:30-10:30)冲高即走\n",
        f"\n⚠️ **风险提示**: 一夜持股法核心是次日高开获利了结，见好就收\n",
        f"\n🔗 **数据来源**: akshare强势股池(stock_zt_pool_strong_em) + 腾讯实时行情\n",
    ])
    
    return "".join(lines)


# ========== 单独测试/运行入口 ==========
if __name__ == "__main__":
    print("=" * 60)
    print("🌙 一夜持股法选股系统 v3.0 (AKShare重构版)")
    print("=" * 60)
    
    results, index_data = screen_overnight_v3()
    report = format_report_v3(results, index_data)
    
    print("\n" + "─" * 60)
    print(report)
    
    if results:
        print("\n[DEBUG_JSON]")
        print(json.dumps(results, ensure_ascii=False, indent=2))
