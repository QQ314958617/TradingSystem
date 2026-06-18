"""
超跌反弹策略 v1.0 — RSI(2)均值回归
====================================
核心逻辑：Larry Connors RSI(2) 均值回归策略
- 买跌不买涨：RSI(2) < 10 时买入（极度超卖）
- 回归即走：收盘价回到5日均线上方时卖出
- 大盘过滤：沪指在200日均线上方才开仓

预期胜率：70-80%
持仓周期：1-3天
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies import BaseStrategy, StrategyRegistry
from datetime import datetime, timezone, timedelta, time as t_time
import requests
import numpy as np
import time as pytime


class MeanReversionStrategy(BaseStrategy):
    """超跌反弹策略 v1.0 — RSI(2)均值回归"""
    
    name = "超跌反弹"
    strategy_type = "mean_reversion"
    description = "RSI(2)均值回归：极度超卖时买入，价格回归5日均线时卖出，胜率70-80%"
    
    def __init__(self, strategy_id: int, config: dict = None):
        super().__init__(strategy_id, config)
        self.config = {
            # 入场条件
            'rsi2_entry': 20,              # RSI(2) < 此值买入（↑原10，牛市切换为回调买入模式）
            'ma200_filter': True,          # 大盘200日均线过滤
            'market_cap_min': 50,          # 流通市值下限(亿)
            'market_cap_max': 500,         # 流通市值上限(亿)（↑原200，接住大盘科技）
            'min_volume': 500000,          # 最小成交量(手)
            'exclude_st': True,            # 排除ST
            'exclude_new': True,           # 排除次新(上市<60天)
            'max_positions': 3,            # 最多同时持有
            'position_size': 10000,        # 单票金额上限
            
            # 出场条件
            'exit_above_ma5': True,        # 收盘价>5日均线时卖出
            'stop_loss': -5.0,             # 止损%（极端情况保护）
            'max_hold_days': 5,            # 最长持有天数
            
            # 买入时间窗口
            'buy_time_start': '14:30',     # 买入窗口开始（比一夜持股早）
            'buy_time_end': '14:55',       # 买入窗口结束
            
            # 卖出时间窗口
            'sell_time_start': '09:35',    # 卖出窗口开始
            'sell_time_end': '14:55',      # 卖出窗口结束（全天可卖）
            
            **(config or {})
        }
    
    def is_buy_time(self) -> bool:
        """是否在买入时间窗口"""
        bj = self.get_bj_time()
        now = bj.time()
        start = t_time(14, 30)
        end = t_time(14, 55)
        return start <= now <= end
    
    def is_sell_time(self) -> bool:
        """是否在卖出时间窗口"""
        bj = self.get_bj_time()
        now = bj.time()
        start = t_time(9, 35)
        end = t_time(14, 55)
        return start <= now <= end
    
    # ═══════════════════════════════════════
    # 大盘环境检查
    # ═══════════════════════════════════════
    
    def check_market_environment(self) -> dict:
        """检查大盘是否在200日均线上方
        
        返回: {'ok': bool, 'price': float, 'ma200': float, 'reason': str}
        """
        try:
            # 获取沪指日K线数据（至少200天）
            prefix = 'sh'
            code = '000001'
            url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,250,qfq'
            resp = requests.get(url, timeout=10)
            data = resp.json()
            
            klines = data.get('data', {}).get(f'{prefix}{code}', {}).get('qfqday', [])
            if not klines:
                klines = data.get('data', {}).get(f'{prefix}{code}', {}).get('day', [])
            
            if len(klines) < 200:
                return {'ok': False, 'price': 0, 'ma200': 0, 'reason': f'K线数据不足({len(klines)}条)'}
            
            # 取收盘价
            closes = [float(k[2]) for k in klines]
            current_price = closes[-1]
            ma200 = np.mean(closes[-200:])
            
            if current_price > ma200:
                return {'ok': True, 'price': current_price, 'ma200': round(ma200, 2), 
                        'reason': f'沪指{current_price}在200日均线{ma200:.0f}上方'}
            else:
                return {'ok': False, 'price': current_price, 'ma200': round(ma200, 2),
                        'reason': f'沪指{current_price}在200日均线{ma200:.0f}下方，不开仓'}
        except Exception as e:
            return {'ok': False, 'price': 0, 'ma200': 0, 'reason': f'获取大盘数据失败: {e}'}
    
    # ═══════════════════════════════════════
    # RSI(2) 计算
    # ═══════════════════════════════════════
    
    def calc_rsi2(self, closes: list) -> float:
        """计算RSI(2)
        
        RSI(2)只看最近2根K线的涨跌幅，极度敏感
        """
        if len(closes) < 3:
            return 50.0  # 数据不足返回中性值
        
        # 计算涨跌幅
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        
        # 只取最近2个变化
        recent = changes[-2:]
        gains = [max(c, 0) for c in recent]
        losses = [abs(min(c, 0)) for c in recent]
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100.0
        if avg_gain == 0:
            return 0.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)
    
    def get_stock_klines(self, code: str, count: int = 20) -> list:
        """获取个股日K线数据"""
        try:
            prefix = 'sh' if code.startswith('6') else 'sz'
            url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,{count},qfq'
            resp = requests.get(url, timeout=10)
            data = resp.json()
            
            klines = data.get('data', {}).get(f'{prefix}{code}', {}).get('qfqday', [])
            if not klines:
                klines = data.get('data', {}).get(f'{prefix}{code}', {}).get('day', [])
            return klines
        except Exception:
            return []
    
    # ═══════════════════════════════════════
    # 选股扫描
    # ═══════════════════════════════════════
    
    def scan_oversold_stocks(self) -> list:
        """扫描RSI(2)<10的超跌股
        
        流程：
        1. 从全市场获取候选池（跌幅靠前的股票）
        2. 逐个计算RSI(2)
        3. 筛选RSI(2) < entry阈值的
        """
        cfg = self.config
        candidates = []
        
        # 从API获取跌幅靠前的股票（超跌候选）
        try:
            resp = requests.get('http://localhost/api/market/fullscan?mode=oversold', timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                pool = data.get('candidates', [])
            else:
                # fallback: 用top接口获取跌幅股
                resp = requests.get('http://localhost/api/market/top?sort=change_asc&limit=50', timeout=15)
                if resp.status_code == 200:
                    pool = resp.json() if isinstance(resp.json(), list) else resp.json().get('stocks', [])
                else:
                    pool = []
        except Exception:
            pool = []
        
        if not pool:
            return []
        
        # 逐个检查RSI(2)
        for stock in pool[:30]:  # 最多检查30只
            code = stock.get('code', '')
            if not code:
                continue
            
            # 基本过滤
            market_cap = stock.get('circulate_mv_yi', stock.get('market_cap', 0))
            if market_cap and (market_cap < cfg['market_cap_min'] or market_cap > cfg['market_cap_max']):
                continue
            
            name = stock.get('name', '')
            if cfg['exclude_st'] and ('ST' in name or '*ST' in name):
                continue
            
            # 获取K线计算RSI(2)
            klines = self.get_stock_klines(code, 10)
            if len(klines) < 5:
                continue
            
            closes = [float(k[2]) for k in klines]
            rsi2 = self.calc_rsi2(closes)
            
            # RSI(2) < 阈值 = 超跌信号
            if rsi2 < cfg['rsi2_entry']:
                # 计算5日均线（用于卖出判断）
                ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
                
                candidates.append({
                    'code': code,
                    'name': name,
                    'price': closes[-1],
                    'rsi2': rsi2,
                    'ma5': round(ma5, 2),
                    'market_cap': market_cap,
                    'change_pct': stock.get('change_pct', 0),
                })
            
            pytime.sleep(0.3)  # API限流
        
        # 按RSI(2)从低到高排序（越低越超卖）
        candidates.sort(key=lambda x: x['rsi2'])
        return candidates
    
    # ═══════════════════════════════════════
    # 卖出决策
    # ═══════════════════════════════════════
    
    def should_sell(self, code: str, cost_price: float, current_price: float,
                    hold_days: int) -> tuple:
        """卖出决策
        
        规则：
        1. 收盘价 > 5日均线 → 卖出（均值回归完成）
        2. 止损 -5% → 卖出
        3. 持有超过5天 → 卖出
        """
        cfg = self.config
        profit_pct = (current_price - cost_price) / cost_price * 100
        
        # 止损（无条件）
        if profit_pct <= cfg['stop_loss']:
            return True, f"止损触发：{profit_pct:.1f}%（≤{cfg['stop_loss']}%）"
        
        # 超时卖出
        if hold_days >= cfg['max_hold_days']:
            return True, f"超时卖出：已持有{hold_days}天（上限{cfg['max_hold_days']}天）"
        
        # 核心卖出条件：价格回到5日均线上方
        if cfg['exit_above_ma5']:
            klines = self.get_stock_klines(code, 10)
            if len(klines) >= 5:
                closes = [float(k[2]) for k in klines]
                ma5 = np.mean(closes[-5:])
                if current_price > ma5:
                    return True, f"均值回归完成：现价{current_price}>{ma5:.2f}(MA5)，盈利{profit_pct:+.1f}%"
        
        return False, ""
    
    # ═══════════════════════════════════════
    # 买入计算
    # ═══════════════════════════════════════
    
    def calc_buy_shares(self, price: float) -> int:
        """计算买入股数（不超过单票上限）"""
        max_amount = self.config['position_size']
        shares = int(max_amount / price / 100) * 100
        if shares == 0:
            shares = 100  # 最少买100股
        return shares


# 注册策略
StrategyRegistry.register(MeanReversionStrategy)
