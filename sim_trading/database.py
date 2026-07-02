"""
数据库层 - SQLite(多策略支持 v2.0)
"""
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

DATABASE_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'trading.db')

def get_db_path():
    os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)
    return DATABASE_FILE

@contextmanager
def get_connection():
    """数据库连接上下文管理器"""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_database():
    """初始化数据库表"""
    with get_connection() as conn:
        c = conn.cursor()

        # 账户表
        c.execute('''
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY,
                cash REAL DEFAULT 50000.0,
                total_value REAL DEFAULT 50000.0,
                total_profit REAL DEFAULT 0.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 持仓表
        c.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                shares INTEGER,
                avg_cost REAL,
                buy_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                strategy_id INTEGER DEFAULT 1,
                position_phase INTEGER DEFAULT 3,
                target_shares INTEGER DEFAULT 0,
                UNIQUE(stock_code, strategy_id)
            )
        ''')

        # 交易记录表
        c.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                action TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                price REAL,
                shares INTEGER,
                amount REAL,
                commission REAL DEFAULT 0,
                profit REAL DEFAULT 0,
                reason TEXT,
                strategy_id INTEGER DEFAULT 1
            )
        ''')

        # 每日复盘表
        c.execute('''
            CREATE TABLE IF NOT EXISTS daily_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                content TEXT,
                strategies TEXT,
                profit REAL DEFAULT 0,
                tags TEXT
            )
        ''')

        # 账户净值历史
        c.execute('''
            CREATE TABLE IF NOT EXISTS equity_curve (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                total_value REAL,
                cash REAL,
                position_value REAL,
                strategy_id INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 策略表
        c.execute('''
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                description TEXT DEFAULT '',
                capital REAL DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                config TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 兼容旧表:添加strategy_id列(如果不存在)
        c.execute('PRAGMA table_info(trades)')
        cols_trades = [r[1] for r in c.fetchall()]
        if 'strategy_id' not in cols_trades:
            c.execute('ALTER TABLE trades ADD COLUMN strategy_id INTEGER DEFAULT 1')
        c.execute('PRAGMA table_info(positions)')
        cols_positions = [r[1] for r in c.fetchall()]
        if 'strategy_id' not in cols_positions:
            c.execute('ALTER TABLE positions ADD COLUMN strategy_id INTEGER DEFAULT 1')
        if 'position_phase' not in cols_positions:
            c.execute('ALTER TABLE positions ADD COLUMN position_phase INTEGER DEFAULT 3')
        if 'target_shares' not in cols_positions:
            c.execute('ALTER TABLE positions ADD COLUMN target_shares INTEGER DEFAULT 0')
        c.execute('PRAGMA table_info(equity_curve)')
        cols_equity = [r[1] for r in c.fetchall()]
        if 'strategy_id' not in cols_equity:
            c.execute('ALTER TABLE equity_curve ADD COLUMN strategy_id INTEGER DEFAULT 0')

        # 兼容旧表:添加initial_capital列
        c.execute('PRAGMA table_info(account)')
        cols_account = [r[1] for r in c.fetchall()]
        if 'initial_capital' not in cols_account:
            c.execute('ALTER TABLE account ADD COLUMN initial_capital REAL DEFAULT 50000.0')
            # 如果总资产已变化,将initial_capital同步为当前total_value(避免旧利润虚高)
            c.execute('SELECT total_value FROM account WHERE id = 1')
            row = c.fetchone()
            if row and row[0] > 50100:
                c.execute('UPDATE account SET initial_capital = total_value WHERE id = 1')
                print(f"  📌 已同步 initial_capital={row[0]} (防止旧数据利润虚高)")

        # 初始化默认策略
        default_strategies = [
            ('ETF轮动', 'etf_rotation', 'ETF动量评分轮动,每日换仓持有最强ETF', 40000.0, 1, '{}'),
            ('小市值', 'small_cap', '399100成分股流通市值排序,每周二调仓持6只', 35000.0, 1, '{}'),
            ('白马', 'white_horse', '沪深300质优股+创业板小盘,大盘择时+月度调仓', 25000.0, 1, '{}'),
        ]
        for s in default_strategies:
            c.execute('''
                INSERT OR IGNORE INTO strategies (name, type, description, capital, is_active, config)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', s)

        # 初始化账户(如果不存在)
        bj_tz = timezone(timedelta(hours=8))
        now_bj = datetime.now(bj_tz).strftime('%Y-%m-%d %H:%M:%S')
        c.execute('SELECT COUNT(*) FROM account')
        if c.fetchone()[0] == 0:
            c.execute('INSERT INTO account (id, cash, total_value, created_at, updated_at) VALUES (1, 50000.0, 50000.0, ?, ?)',
                      (now_bj, now_bj))

        # 性能索引
        c.execute('CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_equity_date ON equity_curve(date)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_equity_date_strategy ON equity_curve(date, strategy_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_positions_strategy ON positions(strategy_id)')

        conn.commit()


# ========== 账户操作 ==========

INITIAL_CAPITAL = 100000.0  # 总账户初始资金

def get_account():
    """获取账户信息"""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM account WHERE id = 1')
        row = c.fetchone()
        if row:
            d = dict(row)
            d['cash'] = round(d['cash'], 2)
            d['total_value'] = round(d['total_value'], 2)
            d['initial_capital'] = d.get('initial_capital', INITIAL_CAPITAL) or INITIAL_CAPITAL
            d['total_profit'] = round(d['total_value'] - d['initial_capital'], 2)
            return d
        return {'cash': INITIAL_CAPITAL, 'total_value': INITIAL_CAPITAL, 'total_profit': 0.0, 'initial_capital': INITIAL_CAPITAL}

def update_account(cash, total_value, total_profit=None):
    """更新账户"""
    bj_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(bj_tz).strftime('%Y-%m-%d %H:%M:%S')

    with get_connection() as conn:
        c = conn.cursor()
        # 获取initial_capital自动计算利润
        c.execute('SELECT initial_capital FROM account WHERE id = 1')
        row = c.fetchone()
        ic = row[0] if row and row[0] else INITIAL_CAPITAL
        if total_profit is None:
            total_profit = round(total_value - ic, 2)
        c.execute('''
            UPDATE account
            SET cash = ?, total_value = ?, total_profit = ?, updated_at = ?
            WHERE id = 1
        ''', (round(cash, 2), round(total_value, 2), round(total_profit, 2), now_bj))
        conn.commit()

# ========== 策略操作 ==========

def get_strategies(active_only=False):
    """获取所有策略"""
    with get_connection() as conn:
        c = conn.cursor()
        if active_only:
            c.execute('SELECT * FROM strategies WHERE is_active = 1 ORDER BY id')
        else:
            c.execute('SELECT * FROM strategies ORDER BY id')
        return [dict(row) for row in c.fetchall()]

def get_strategy(strategy_id):
    """获取单个策略"""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM strategies WHERE id = ?', (strategy_id,))
        row = c.fetchone()
        return dict(row) if row else None

def get_strategy_by_type(strategy_type):
    """按类型获取策略"""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM strategies WHERE type = ? ORDER BY id LIMIT 1', (strategy_type,))
        row = c.fetchone()
        return dict(row) if row else None

def update_strategy_capital(strategy_id, capital):
    """更新策略资金分配"""
    bj_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(bj_tz).strftime('%Y-%m-%d %H:%M:%S')
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('UPDATE strategies SET capital = ?, updated_at = ? WHERE id = ?',
                  (round(capital, 2), now_bj, strategy_id))
        conn.commit()

def update_strategy_activity(strategy_id, is_active):
    """启用/禁用策略"""
    bj_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(bj_tz).strftime('%Y-%m-%d %H:%M:%S')
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('UPDATE strategies SET is_active = ?, updated_at = ? WHERE id = ?',
                  (1 if is_active else 0, now_bj, strategy_id))
        conn.commit()

def get_total_strategies_capital():
    """获取所有活跃策略的总分配资金"""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('SELECT SUM(capital) FROM strategies WHERE is_active = 1')
        return c.fetchone()[0] or 0.0

# ========== 持仓操作 ==========

def get_positions(strategy_id=None):
    """获取持仓(可选按策略过滤)"""
    with get_connection() as conn:
        c = conn.cursor()
        if strategy_id:
            c.execute('SELECT * FROM positions WHERE strategy_id = ?', (strategy_id,))
        else:
            c.execute('SELECT * FROM positions ORDER BY strategy_id')
        return [dict(row) for row in c.fetchall()]

def get_position(stock_code, strategy_id=None):
    """获取单只股票持仓（可按策略过滤）"""
    with get_connection() as conn:
        c = conn.cursor()
        if strategy_id:
            c.execute('SELECT * FROM positions WHERE stock_code = ? AND strategy_id = ?', (stock_code, strategy_id))
        else:
            c.execute('SELECT * FROM positions WHERE stock_code = ?', (stock_code,))
        row = c.fetchone()
        return dict(row) if row else None

def upsert_position(stock_code, stock_name, shares, avg_cost, buy_date=None, strategy_id=1, position_phase=None, target_shares=None):
    """更新持仓（按stock_code+strategy_id唯一）"""
    bj_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(bj_tz).strftime('%Y-%m-%d %H:%M:%S')

    with get_connection() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO positions (stock_code, stock_name, shares, avg_cost, buy_date, created_at, strategy_id, position_phase, target_shares)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, strategy_id) DO UPDATE SET
                stock_name = excluded.stock_name,
                shares = excluded.shares,
                avg_cost = excluded.avg_cost,
                position_phase = COALESCE(excluded.position_phase, positions.position_phase),
                target_shares = COALESCE(excluded.target_shares, positions.target_shares)
        ''', (stock_code, stock_name, shares, round(avg_cost, 2), buy_date or now_bj, now_bj, strategy_id,
              position_phase, target_shares))
        conn.commit()

def delete_position(stock_code, strategy_id=None):
    """删除持仓（按stock_code+strategy_id精确删除）"""
    with get_connection() as conn:
        c = conn.cursor()
        if strategy_id:
            c.execute('DELETE FROM positions WHERE stock_code = ? AND strategy_id = ?', (stock_code, strategy_id))
        else:
            c.execute('DELETE FROM positions WHERE stock_code = ?', (stock_code,))
        conn.commit()

# ========== 交易记录 ==========

def add_trade(action, stock_code, stock_name, price, shares, amount, commission=0, profit=0, reason='', strategy_id=1):
    """添加交易记录"""
    bj_tz = timezone(timedelta(hours=8))
    bj_time = datetime.now(bj_tz).strftime('%Y-%m-%d %H:%M:%S')

    with get_connection() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO trades (action, stock_code, stock_name, price, shares, amount, commission, profit, reason, timestamp, strategy_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (action, stock_code, stock_name, round(price, 2), shares, round(amount, 2), round(commission, 2), round(profit, 2), reason, bj_time, strategy_id))
        conn.commit()
        return c.lastrowid

def get_trades(limit=100, offset=0, strategy_id=None):
    """获取交易记录(支持分页+策略过滤，排除monitor监控记录)"""
    with get_connection() as conn:
        c = conn.cursor()
        if strategy_id:
            c.execute("SELECT * FROM trades WHERE strategy_id = ? AND action != 'monitor' ORDER BY timestamp DESC LIMIT ? OFFSET ?", (strategy_id, limit, offset))
        else:
            c.execute("SELECT * FROM trades WHERE action != 'monitor' ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset))
        return [dict(row) for row in c.fetchall()]


def get_trades_count(strategy_id=None):
    """获取交易记录总数(排除monitor监控记录)"""
    with get_connection() as conn:
        c = conn.cursor()
        if strategy_id:
            c.execute("SELECT COUNT(*) FROM trades WHERE strategy_id = ? AND action != 'monitor'", (strategy_id,))
        else:
            c.execute("SELECT COUNT(*) FROM trades WHERE action != 'monitor'")
        return c.fetchone()[0]

# ========== 复盘记录 ==========

def add_review(date, content, strategies='', profit=0, tags=''):
    """添加复盘"""
    bj_tz = timezone(timedelta(hours=8))
    bj_time = datetime.now(bj_tz).strftime('%Y-%m-%d %H:%M:%S')

    with get_connection() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO daily_reviews (date, content, strategies, profit, tags, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (date, content, strategies, round(float(profit or 0), 2), tags, bj_time))
        conn.commit()
        return c.lastrowid

def get_reviews(limit=50):
    """获取复盘记录"""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM daily_reviews ORDER BY timestamp DESC LIMIT ?', (limit,))
        return [dict(row) for row in c.fetchall()]

def get_reviews_paged(offset=0, limit=10):
    """获取复盘记录(分页)"""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM daily_reviews')
        total = c.fetchone()[0]
        c.execute('SELECT * FROM daily_reviews ORDER BY timestamp DESC LIMIT ? OFFSET ?', (limit, offset))
        return total, [dict(row) for row in c.fetchall()]

# ========== 净值曲线 ==========

def add_equity_record(date, total_value, cash, position_value, strategy_id=0):
    """记录净值"""
    bj_tz = timezone(timedelta(hours=8))
    bj_time = datetime.now(bj_tz).strftime('%Y-%m-%d %H:%M:%S')

    with get_connection() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO equity_curve (date, total_value, cash, position_value, strategy_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (date, round(total_value, 2), round(cash, 2), round(position_value, 2), strategy_id, bj_time))
        conn.commit()

def get_equity_curve(days=30, strategy_id=None):
    """获取净值曲线数据"""
    with get_connection() as conn:
        c = conn.cursor()
        if strategy_id:
            c.execute('''
                SELECT * FROM equity_curve
                WHERE strategy_id = ?
                ORDER BY date ASC
                LIMIT ?
            ''', (strategy_id, days))
        else:
            c.execute('''
                SELECT * FROM equity_curve
                ORDER BY id DESC
                LIMIT ?
            ''', (days,))
        rows = [dict(row) for row in c.fetchall()]
        rows.reverse()
        return rows

# ========== 统计分析 ==========

def get_recently_sold_stocks(hours=48, strategy_id=None):
    """获取最近N小时内卖出的股票代码列表"""
    bj_tz = timezone(timedelta(hours=8))
    cutoff = datetime.now(bj_tz) - timedelta(hours=hours)
    cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')

    with get_connection() as conn:
        c = conn.cursor()
        if strategy_id:
            c.execute('''
                SELECT DISTINCT stock_code, stock_name, profit, timestamp
                FROM trades
                WHERE action = 'sell' AND timestamp >= ? AND strategy_id = ?
                ORDER BY timestamp DESC
            ''', (cutoff_str, strategy_id))
        else:
            c.execute('''
                SELECT DISTINCT stock_code, stock_name, profit, timestamp
                FROM trades
                WHERE action = 'sell' AND timestamp >= ?
                ORDER BY timestamp DESC
            ''', (cutoff_str,))
        return [dict(row) for row in c.fetchall()]

def get_trade_stats(strategy_id=None):
    """获取交易统计(可选按策略过滤)"""
    with get_connection() as conn:
        c = conn.cursor()
        # 卖出次数
        if strategy_id:
            c.execute("SELECT COUNT(*) FROM trades WHERE action = 'sell' AND strategy_id = ?", (strategy_id,))
        else:
            c.execute("SELECT COUNT(*) FROM trades WHERE action = 'sell'")
        total_closed = c.fetchone()[0]
        # 盈利卖出
        if strategy_id:
            c.execute("SELECT COUNT(*) FROM trades WHERE action = 'sell' AND profit > 0 AND strategy_id = ?", (strategy_id,))
        else:
            c.execute("SELECT COUNT(*) FROM trades WHERE action = 'sell' AND profit > 0")
        win_trades = c.fetchone()[0]
        # 亏损卖出
        if strategy_id:
            c.execute("SELECT COUNT(*) FROM trades WHERE action = 'sell' AND profit < 0 AND strategy_id = ?", (strategy_id,))
        else:
            c.execute("SELECT COUNT(*) FROM trades WHERE action = 'sell' AND profit < 0")
        loss_trades = c.fetchone()[0]
        # 总盈利
        if strategy_id:
            c.execute('SELECT SUM(profit) FROM trades WHERE profit > 0 AND strategy_id = ?', (strategy_id,))
        else:
            c.execute('SELECT SUM(profit) FROM trades WHERE profit > 0')
        total_profit = round(c.fetchone()[0] or 0, 2)
        # 总亏损
        if strategy_id:
            c.execute('SELECT SUM(ABS(profit)) FROM trades WHERE profit < 0 AND strategy_id = ?', (strategy_id,))
        else:
            c.execute('SELECT SUM(ABS(profit)) FROM trades WHERE profit < 0')
        total_loss = round(c.fetchone()[0] or 0, 2)
        # 单笔最大盈利
        if strategy_id:
            c.execute('SELECT MAX(profit) FROM trades WHERE action = "sell" AND strategy_id = ?', (strategy_id,))
        else:
            c.execute('SELECT MAX(profit) FROM trades WHERE action = "sell"')
        max_profit = round(c.fetchone()[0] or 0, 2)
        # 单笔最大亏损
        if strategy_id:
            c.execute('SELECT MIN(profit) FROM trades WHERE action = "sell" AND strategy_id = ?', (strategy_id,))
        else:
            c.execute('SELECT MIN(profit) FROM trades WHERE action = "sell"')
        max_loss = round(c.fetchone()[0] or 0, 2)

        return {
            'total_trades': total_closed,
            'win_trades': win_trades,
            'loss_trades': loss_trades,
            'win_rate': round(win_trades / total_closed * 100, 2) if total_closed > 0 else 0,
            'total_profit': total_profit,
            'total_loss': total_loss,
            'net_profit': round(total_profit - total_loss, 2),
            'max_profit': max_profit,
            'max_loss': max_loss
        }
