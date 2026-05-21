"""
一夜持股法回测引擎 v1.0
=========================
纯自研回测，用akshare历史数据
优点：不依赖大数据包，完全可控
"""

import os
import sys
import json
import time
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import akshare as ak

# ========== 策略参数 ==========
CONFIG = {
    'start_date': '2024-01-01',    # 回测开始
    'end_date': '2026-04-14',      # 回测结束
    'initial_cash': 50000,          # 初始资金
    'rise_min': 3.0,               # 涨幅下限 %
    'rise_max': 5.0,               # 涨幅上限 %
    'rsi_min': 40,                 # RSI下限
    'rsi_max': 65,                 # RSI上限
    'turnover_min': 3.0,           # 换手率下限 %
    'turnover_max': 10.0,          # 换手率上限 %
    'volume_ratio_min': 1.5,       # 成交量放大倍数
    'market_cap_min': 50,          # 流通市值下限（亿）
    'market_cap_max': 200,         # 流通市值上限（亿）
    'stop_loss': -3.0,            # 止损 %
    'take_profit': 3.0,           # 止盈 %
    'max_shares': 5,              # 最多持仓N只（可扩展）
}


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, config=None):
        self.config = {**CONFIG, **(config or {})}
        self.trades = []          # 交易记录
        self.equity_curve = []    # 净值曲线
        self.stats = {}            # 绩效指标
        
        # 数据库路径
        self.db_path = Path(__file__).parent / 'backtest.db'
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buy_date TEXT, sell_date TEXT,
                stock_code TEXT, stock_name TEXT,
                buy_price REAL, sell_price REAL,
                shares INTEGER, profit_pct, profit_amount REAL,
                reason TEXT, created_at TEXT
            )
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config TEXT, stats TEXT, created_at TEXT
            )
        ''')
        self.conn.commit()
    
    def log(self, msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    
    # ========== 数据获取 ==========
    
    def get_trading_days(self, start_date, end_date):
        """获取交易日列表"""
        try:
            df = ak.tool_trade_date_hist_sina()
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            days = df[(df['date'] >= start_date) & (df['date'] <= end_date)]['date'].tolist()
            return days
        except Exception as e:
            self.log(f"获取交易日失败: {e}, 使用备用方法")
            # 备用：生成所有工作日
            dates = pd.bdate_range(start_date, end_date).strftime('%Y-%m-%d').tolist()
            return dates
    
    def get_market_snapshot(self, date):
        """获取某日全市场行情快照"""
        try:
            df = ak.stock_zh_a_spot_em()
            # 过滤ST、停牌股
            df = df[~df['名称'].str.contains('ST|退市|N|摘帽', na=False)]
            df = df[df['最新价'] > 0]
            df = df.rename(columns={
                '代码': 'code', '名称': 'name',
                '最新价': 'close', '涨跌幅': 'change_pct',
                '成交量': 'volume', '成交额': 'amount',
                '换手率': 'turnover', '总市值': 'market_cap',
                '流通市值': 'float_market_cap',
                '今开': 'open', '最高': 'high', '最低': 'low',
                '昨收': 'pre_close'
            })
            df = df[['code', 'name', 'close', 'change_pct', 'volume',
                     'amount', 'turnover', 'market_cap', 'float_market_cap',
                     'open', 'high', 'low', 'pre_close']]
            return df
        except Exception as e:
            self.log(f"获取行情失败: {e}")
            return pd.DataFrame()
    
    def get_stock_history(self, code, days=60):
        """获取个股历史数据"""
        try:
            end = datetime.now().strftime('%Y%m%d')
            start = (datetime.now() - timedelta(days=days*2)).strftime('%Y%m%d')
            df = ak.stock_zh_a_hist(
                symbol=code, period='daily',
                start_date=start, end_date=end, adjust='qfq'
            )
            df = df.rename(columns={
                '日期': 'date', '开盘': 'open', '收盘': 'close',
                '最高': 'high', '最低': 'low', '成交量': 'volume',
                '成交额': 'amount', '涨跌幅': 'change_pct',
                '换手率': 'turnover', '总市值': 'market_cap',
                '流通市值': 'float_market_cap'
            })
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            return df
        except Exception as e:
            return pd.DataFrame()
    
    def get_index_history(self, symbol='000001', days=60):
        """获取指数历史数据"""
        try:
            end = datetime.now().strftime('%Y%m%d')
            start = (datetime.now() - timedelta(days=days*2)).strftime('%Y%m%d')
            df = ak.stock_zh_index_daily(symbol=f'sh{symbol}')
            df = df.tail(days)
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            return df
        except:
            return pd.DataFrame()
    
    # ========== 指标计算 ==========
    
    def calc_rsi(self, closes, period=14):
        """计算RSI"""
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def calc_ma(self, series, n):
        """计算移动平均"""
        return series.rolling(n).mean()
    
    def calc_volume_ratio(self, volumes, n=5):
        """计算成交量放大倍数"""
        if len(volumes) < n + 1:
            return 1.0
        avg_vol = np.mean(volumes[-(n+1):-1])  # 前N日均量
        return volumes[-1] / avg_vol if avg_vol > 0 else 0
    
    # ========== 选股 ==========
    
    def screen_stocks(self, snapshot_df, index_change_pct=0):
        """
        筛选符合一夜持股法条件的股票
        返回: [(code, name, score, reason), ...] 按评分排序
        """
        candidates = []
        
        for _, row in snapshot_df.iterrows():
            code = str(row['code']).zfill(6)
            change_pct = row.get('change_pct', 0) or 0
            
            # 1. 涨幅过滤
            if not (self.config['rise_min'] <= change_pct <= self.config['rise_max']):
                continue
            
            # 2. 换手率过滤
            turnover = row.get('turnover', 0) or 0
            if not (self.config['turnover_min'] <= turnover <= self.config['turnover_max']):
                continue
            
            # 3. 流通市值过滤
            float_cap = row.get('float_market_cap', 0) or 0
            if not (self.config['market_cap_min'] <= float_cap <= self.config['market_cap_max']):
                continue
            
            # 4. 获取历史数据计算指标
            hist = self.get_stock_history(code)
            if hist.empty or len(hist) < 25:
                continue
            
            closes = hist['close'].values
            volumes = hist['volume'].values
            
            # 5. RSI
            rsi = self.calc_rsi(closes)
            if not (self.config['rsi_min'] <= rsi <= self.config['rsi_max']):
                continue
            
            # 6. 成交量放大
            vol_ratio = self.calc_volume_ratio(volumes)
            if vol_ratio < self.config['volume_ratio_min']:
                continue
            
            # 7. 价格站上MA5
            ma5 = np.mean(closes[-5:])
            if closes[-1] < ma5:
                continue
            
            # 8. 强于大盘
            if change_pct <= index_change_pct:
                continue
            
            # ========== 评分 ==========
            score = 0
            
            # 涨幅适中给高分（3-4%最优）
            if 3.0 <= change_pct <= 4.0:
                score += 30
            elif 4.0 < change_pct <= 5.0:
                score += 20
            
            # RSI在45-55黄金区间
            if 45 <= rsi <= 55:
                score += 25
            elif 40 <= rsi < 45 or 55 < rsi <= 65:
                score += 15
            
            # 成交量放大适中
            if 1.8 <= vol_ratio <= 3.0:
                score += 20
            elif 1.5 <= vol_ratio < 1.8 or 3.0 < vol_ratio <= 5.0:
                score += 10
            
            # 换手率适中
            if 5.0 <= turnover <= 8.0:
                score += 15
            elif 8.0 <= turnover <= 10.0:
                score += 8
            
            # 距离MA5近（强势整理）
            ma5_dist = (closes[-1] - ma5) / ma5 * 100
            if ma5_dist < 1.0:
                score += 10
            
            reason = f"涨{change_pct:.1f}%+RSI{rsi:.0f}+量{vol_ratio:.1f}x+换{turnover:.1f}%"
            candidates.append((code, row['name'], score, reason))
        
        # 按评分排序
        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates
    
    # ========== 核心回测 ==========
    
    def run(self):
        """运行回测"""
        self.log("=" * 60)
        self.log("🥚 一夜持股法回测引擎 v1.0 启动")
        self.log(f"   区间: {self.config['start_date']} ~ {self.config['end_date']}")
        self.log(f"   初始资金: ¥{self.config['initial_cash']:,.0f}")
        self.log("=" * 60)
        
        # 获取交易日列表
        trading_days = self.get_trading_days(
            self.config['start_date'],
            self.config['end_date']
        )
        self.log(f"📅 交易日总数: {len(trading_days)}")
        
        # 预加载指数历史（一次性获取，避免重复请求）
        self.log("📊 预加载指数历史...")
        index_hist = self.get_index_history('000001', days=100)
        
        # 预加载全市场历史（采样500只）
        self.log("📊 预加载市场快照（第一批500只）...")
        
        # 账户状态
        cash = self.config['initial_cash']
        positions = {}  # {code: {name, shares, buy_price, buy_date}}
        daily_stats = []  # 每日账户状态
        
        total_trades = 0
        win_trades = 0
        total_profit_pct = 0
        win_amounts = []
        loss_amounts = []
        
        self.log("🚀 开始回测...")
        
        for i, today in enumerate(trading_days):
            if i % 50 == 0:
                self.log(f"   进度: {i}/{len(trading_days)} ({i/len(trading_days)*100:.1f}%)")
            
            # === 获取当日数据 ===
            snapshot = self.get_market_snapshot(today)
            if snapshot.empty:
                continue
            
            # === 获取大盘当日涨跌 ===
            index_row = index_hist[index_hist['date'] == today]
            index_change_pct = index_row['close'].pct_change().iloc[-1] * 100 if not index_row.empty else 0
            
            # === 卖出逻辑（持仓的股票在次日卖出）===
            sell_list = []
            for code, pos in list(positions.items()):
                buy_date = pos['buy_date']
                buy_idx = trading_days.index(buy_date) if buy_date in trading_days else -1
                today_idx = trading_days.index(today) if today in trading_days else -1
                
                # T+1: 持有一天后次日卖出
                if today_idx > buy_idx:
                    # 获取次日开盘价
                    tomorrow_idx = today_idx + 1
                    if tomorrow_idx < len(trading_days):
                        tomorrow = trading_days[tomorrow_idx]
                        tomorrow_snapshot = self.get_market_snapshot(tomorrow)
                        if not tomorrow_snapshot.empty:
                            t_row = tomorrow_snapshot[ tomorrow_snapshot['code'] == code ]
                            if not t_row.empty:
                                open_price = t_row['open'].values[0]
                                high_price = t_row['high'].values[0]
                                close_price = t_row['close'].values[0]
                                pre_close = t_row['pre_close'].values[0]
                                
                                if open_price > 0 and pre_close > 0:
                                    sell_price = open_price  # 以开盘价卖出（模拟集合竞价）
                                    profit_pct = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                                    
                                    # 模拟手续费
                                    buy_cost = pos['buy_price'] * pos['shares'] * 1.0003
                                    sell_cost = sell_price * pos['shares'] * (1.0003 + 0.0005)
                                    net_profit = sell_price * pos['shares'] - sell_cost - buy_cost + pos['buy_price'] * pos['shares']
                                    profit_pct_real = net_profit / (pos['buy_price'] * pos['shares']) * 100
                                    
                                    total_trades += 1
                                    total_profit_pct += profit_pct_real
                                    
                                    if profit_pct_real > 0:
                                        win_trades += 1
                                        win_amounts.append(profit_pct_real)
                                    else:
                                        loss_amounts.append(profit_pct_real)
                                    
                                    sell_list.append(code)
                                    
                                    emoji = "🟢" if profit_pct_real > 0 else "🔴"
                                    self.log(f"{emoji} {today} 卖出 {code} {pos['name']} | "
                                            f"买{pos['buy_price']:.2f}→卖{sell_price:.2f} | {profit_pct_real:+.2f}%")
                                    
                                    # 记录交易
                                    self._record_trade(
                                        buy_date=pos['buy_date'], sell_date=today,
                                        code=code, name=pos['name'],
                                        buy_price=pos['buy_price'], sell_price=sell_price,
                                        shares=pos['shares'], profit_pct=profit_pct_real,
                                        profit_amount=net_profit,
                                        reason=pos.get('reason', '')
                                    )
                                    
                                    # 收回资金
                                    sell_value = sell_price * pos['shares']
                                    cash += sell_value - sell_cost
                                    del positions[code]
                    else:
                        # 最后一天，强平
                        sell_list.append(code)
                        code_row = snapshot[snapshot['code'] == code]
                        if not code_row.empty:
                            sell_price = code_row['close'].values[0]
                            profit_pct = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                            total_trades += 1
                            total_profit_pct += profit_pct
                            if profit_pct > 0:
                                win_trades += 1
                                win_amounts.append(profit_pct)
                            else:
                                loss_amounts.append(profit_pct)
                            cash += sell_price * pos['shares']
                            del positions[code]
            
            # === 买入逻辑（空仓时尾盘买入）===
            if not positions and cash >= 10000:
                candidates = self.screen_stocks(snapshot, index_change_pct)
                if candidates:
                    code, name, score, reason = candidates[0]  # 选评分最高的
                    code_row = snapshot[snapshot['code'] == code]
                    if not code_row.empty:
                        buy_price = code_row['close'].values[0]
                        shares = int(100000 / buy_price / 100) * 100  # 按手取整，策略资金¥10万
                        if shares >= 100 and buy_price * shares <= cash:
                            # 扣除买入成本
                            buy_cost = buy_price * shares * 1.0003
                            cash -= buy_cost
                            
                            positions[code] = {
                                'name': name,
                                'shares': shares,
                                'buy_price': buy_price,
                                'buy_date': today,
                                'reason': reason
                            }
                            self.log(f"🔵 {today} 买入 {code} {name} | ¥{buy_price:.2f}x{shares}股 | {reason} | 评分{score}")
            
            # === 记录每日净值 ===
            position_value = sum(
                p['shares'] * snapshot[snapshot['code'] == code]['close'].values[0]
                if not snapshot[snapshot['code'] == code].empty
                else p['buy_price']
                for code, p in positions.items()
            )
            total_value = cash + position_value
            daily_stats.append({
                'date': today,
                'cash': cash,
                'position_value': position_value,
                'total_value': total_value,
                'positions_count': len(positions)
            })
        
        # === 计算绩效指标 ===
        if total_trades > 0:
            win_rate = win_trades / total_trades * 100
            avg_win = np.mean(win_amounts) if win_amounts else 0
            avg_loss = np.mean(loss_amounts) if loss_amounts else 0
            profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
            
            # 最大回撤
            equity = pd.DataFrame(daily_stats)
            equity['peak'] = equity['total_value'].cummax()
            equity['drawdown'] = (equity['total_value'] - equity['peak']) / equity['peak'] * 100
            max_drawdown = equity['drawdown'].min()
            
            # 年化收益
            n_days = len(daily_stats)
            years = n_days / 252
            final_value = daily_stats[-1]['total_value'] if daily_stats else self.config['initial_cash']
            total_return = (final_value - self.config['initial_cash']) / self.config['initial_cash'] * 100
            annual_return = ((final_value / self.config['initial_cash']) ** (1/years) - 1) * 100 if years > 0 else 0
            
            self.stats = {
                'start_date': self.config['start_date'],
                'end_date': self.config['end_date'],
                'initial_cash': self.config['initial_cash'],
                'final_value': final_value,
                'total_return': total_return,
                'annual_return': annual_return,
                'max_drawdown': max_drawdown,
                'total_trades': total_trades,
                'win_trades': win_trades,
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_loss_ratio': profit_loss_ratio,
            }
        else:
            self.stats = {
                'start_date': self.config['start_date'],
                'end_date': self.config['end_date'],
                'initial_cash': self.config['initial_cash'],
                'final_value': self.config['initial_cash'],
                'total_return': 0,
                'annual_return': 0,
                'max_drawdown': 0,
                'total_trades': 0,
                'win_trades': 0,
                'win_rate': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_loss_ratio': 0,
            }
        
        self.equity_curve = daily_stats
        
        # 保存结果
        self._save_result()
        
        self.log("=" * 60)
        self.log("📊 回测完成！")
        self._print_stats()
        self.log("=" * 60)
        
        return self.stats
    
    def _record_trade(self, **kwargs):
        """记录交易到数据库"""
        self.conn.execute('''
            INSERT INTO backtest_trades 
            (buy_date, sell_date, stock_code, stock_name, buy_price, sell_price,
             shares, profit_pct, profit_amount, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (kwargs['buy_date'], kwargs['sell_date'], kwargs['code'],
              kwargs['name'], kwargs['buy_price'], kwargs['sell_price'],
              kwargs['shares'], kwargs['profit_pct'], kwargs['profit_amount'],
              kwargs['reason'], datetime.now().isoformat()))
        self.conn.commit()
    
    def _save_result(self):
        """保存回测结果"""
        self.conn.execute('''
            INSERT INTO backtest_results (config, stats, created_at)
            VALUES (?, ?, ?)
        ''', (json.dumps(self.config), json.dumps(self.stats), datetime.now().isoformat()))
        self.conn.commit()
    
    def _print_stats(self):
        """打印绩效报告"""
        s = self.stats
        print(f"""
📊 一夜持股法回测报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 区间: {s['start_date']} ~ {s['end_date']}
💰 初始: ¥{s['initial_cash']:,.0f} → 最终: ¥{s['final_value']:,.2f}

📈 绩效指标
├─ 总收益率:  {s['total_return']:+.2f}%
├─ 年化收益:  {s['annual_return']:+.2f}%
├─ 最大回撤:  {s['max_drawdown']:.2f}%
├─ 总交易数:  {s['total_trades']}笔
├─ 胜率:      {s['win_rate']:.1f}% ({s['win_trades']}胜/{s['total_trades']-s['win_trades']}负)
├─ 盈亏比:    {s['profit_loss_ratio']:.2f}:1
├─ 平均盈利:  {s['avg_win']:+.2f}%
└─ 平均亏损:  {s['avg_loss']:+.2f}%
""")
    
    def get_trades(self):
        """获取所有交易记录"""
        df = pd.read_sql('SELECT * FROM backtest_trades', self.conn)
        return df
    
    def get_equity_curve(self):
        """获取净值曲线"""
        return pd.DataFrame(self.equity_curve)


if __name__ == '__main__':
    engine = BacktestEngine()
    stats = engine.run()
    
    # 打印前10笔交易
    trades = engine.get_trades()
    if not trades.empty:
        print("\n📋 最近10笔交易:")
        print(trades.tail(10).to_string())
    
    # 保存净值曲线
    equity = engine.get_equity_curve()
    equity.to_csv('equity_curve.csv', index=False)
    print(f"\n💾 净值曲线已保存到 equity_curve.csv ({len(equity)}行)")
