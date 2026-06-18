"""
一夜持股法策略模块
===================
尾盘14:50-14:55买入，次日早盘09:30-10:30卖出
超短线一夜持股，-2%止损，+5%~8%止盈
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies import BaseStrategy, StrategyRegistry
from datetime import datetime, timezone, timedelta, time as t_time


class OvernightStrategy(BaseStrategy):
    """一夜持股法策略"""
    
    name = "一夜持股法"
    strategy_type = "overnight"
    description = "尾盘14:50-14:55买入，次日早盘09:30-10:30卖出，超短线一夜持股"
    
    def __init__(self, strategy_id: int, config: dict = None):
        super().__init__(strategy_id, config)
        self.config = {
            'rise_min': 3.0,          # 最小涨幅%（牛市放宽至3-10%，容纳更强走势）
            'rise_max': 10.0,         # 最大涨幅%（↑原5%，牛市龙头常涨8%+）
            'rsi_min': 40,            # RSI下限
            'rsi_max': 80,            # RSI上限（↑原65，强势趋势股RSI可达70-80）
            'turnover_min': 2.0,      # 换手率下限%（↓原3%，让部分温和放量股进来）
            'turnover_max': 15.0,     # 换手率上限%（↑原10%，牛市龙头换手率高）
            'volume_ratio_min': 1.2,  # 成交量放大倍数（↓原1.5，牛市中主流股保持均量）
            'market_cap_min': 30,     # 流通市值下限(亿)（↓原50，让中小盘也能入选）
            'market_cap_max': 500,    # 流通市值上限(亿)（↑原200，容纳科技中盘龙头）
            'stop_loss': -2.0,        # 止损%
            'take_profit_min': 4.0,   # 止盈下限%（↓原5%，牛市波动大适度降低预期）
            'take_profit_max': 10.0,  # 止盈上限%（↑原8%，牛市冲高空间更大）
            'max_positions': 3,       # 最多同时持3只
            'position_size': 30000,   # 单票建仓¥30,000
            'buy_time_start': '14:50',  # 买入窗口开始
            'buy_time_end': '14:55',    # 买入窗口结束
            'sell_time_start': '09:30', # 卖出窗口开始
            'sell_time_end': '10:30',   # 卖出窗口结束
            ** (config or {})
        }
    
    def is_buy_time(self) -> bool:
        """是否在买入时间窗口"""
        bj = self.get_bj_time()
        now = bj.time()
        start = t_time(14, 50)
        end = t_time(14, 55)
        return start <= now <= end
    
    def is_sell_time(self) -> bool:
        """是否在卖出时间窗口"""
        bj = self.get_bj_time()
        now = bj.time()
        start = t_time(9, 30)
        end = t_time(10, 30)
        return start <= now <= end
    
    def get_screener_module(self):
        """返回选股器模块"""
        from overnight_screener import run_screener
        return run_screener
    
    def get_buy_criteria_description(self) -> str:
        """获取买入条件描述"""
        cfg = self.config
        return (
            f"涨幅{cfg['rise_min']}%-{cfg['rise_max']}%、"
            f"成交量>{cfg['volume_ratio_min']}x、"
            f"换手率{cfg['turnover_min']}%-{cfg['turnover_max']}%、"
            f"流通市值{cfg['market_cap_min']}-{cfg['market_cap_max']}亿、"
            f"RSI < {cfg['rsi_max']}、"
            f"站上分时均价线、强于大盘"
        )


# 注册策略
StrategyRegistry.register(OvernightStrategy)
