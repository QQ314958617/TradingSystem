#!/usr/bin/env python3
"""
Cron调度器 - 用纯os.system/subprocess执行脚本，不依赖模型
直接在Gateway host上通过exec来周期执行。

用法：python3 cron_daemon_scheduler.py &
"""
import subprocess
import time
import os
from datetime import datetime, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# 任务列表: (名字, 脚本名, cron表达式模拟)
TASKS = {
    "overnight_sell": {
        "script": "run_overnight_sell.py",
        "check_minutes": [list(range(9*60, 10*60+30, 5))]  # 09:00-10:30 每5分钟
    },
    "value_stop_10": {
        "script": "run_value_stop.py",
        "check_minutes": [10*60]  # 10:00
    },
    "trend_scan": {
        "script": "run_trend_scan.py",
        "check_minutes": [10*60]  # 10:00
    },
    "value_stop_14": {
        "script": "run_value_stop.py",
        "check_minutes": [14*60]  # 14:00
    },
    "overnight_scan": {
        "script": "run_overnight_scan.py",
        "check_minutes": [14*60 + 50]  # 14:50
    },
    "overnight_buy": {
        "script": "run_overnight_buy.py",
        "check_minutes": [14*60 + 55]  # 14:55
    },
    "daily_review": {
        "script": "run_daily_review.py",
        "check_minutes": [15*60 + 30]  # 15:30
    },
    "value_scan_mon": {
        "script": "run_value_scan.py",
        "check_minutes": [9*60 + 30],  # 周一09:30
        "weekday_only": [0]
    }
}

last_run = {}

def should_run(task_name, cfg):
    now = datetime.now()
    h, m = now.hour, now.minute
    
    # 检查工作日
    weekday = now.weekday()  # 0=周一
    if "weekday_only" in cfg and weekday not in cfg["weekday_only"]:
        return False
    if weekday >= 5:  # 周末不执行
        return False
    
    current_minutes = h * 60 + m
    check_list = cfg["check_minutes"]
    
    # 简单列表方式
    if isinstance(check_list, list) and not isinstance(check_list[0], list):
        return current_minutes in check_list
    elif isinstance(check_list, list) and isinstance(check_list[0], list):
        for block in check_list:
            if current_minutes in block:
                return True
    
    return False

def main():
    print(f"[cron_scheduler] 启动于 {datetime.now().isoformat()}", flush=True)
    print(f"[cron_scheduler] 脚本目录: {SCRIPTS_DIR}", flush=True)
    
    while True:
        now = datetime.now()
        key = f"{now.hour}:{now.minute}"
        
        for task_name, cfg in TASKS.items():
            if should_run(task_name, cfg):
                last_key = last_run.get(task_name)
                if last_key == key:
                    continue  # 本分钟已执行
                
                last_run[task_name] = key
                script_path = os.path.join(SCRIPTS_DIR, cfg["script"])
                
                print(f"[{now.strftime('%H:%M:%S')}] 执行 {task_name} -> {cfg['script']}", flush=True)
                
                try:
                    result = subprocess.run(
                        ["python3", script_path],
                        capture_output=True, text=True, timeout=120
                    )
                    
                    # 写日志
                    log_dir = "/tmp/cron_logs"
                    os.makedirs(log_dir, exist_ok=True)
                    log_file = os.path.join(log_dir, f"{task_name}_{now.strftime('%H%M%S')}.log")
                    with open(log_file, "w") as f:
                        f.write(result.stdout)
                        if result.stderr:
                            f.write("\n--- STDERR ---\n")
                            f.write(result.stderr)
                        f.write(f"\n--- RC={result.returncode} ---\n")
                    
                    if result.returncode != 0:
                        print(f"[WARN] {task_name} 完成 (RC={result.returncode})")
                        if result.stderr:
                            print(f"  stderr: {result.stderr[:200]}")
                    else:
                        output_lines = result.stdout.strip().split("\n")
                        summary = [l for l in output_lines if "->" in l or "买入" in l or "止损" in l or "止盈" in l or "成功" in l or "跳过" in l]
                        if summary:
                            for s in summary[:5]:
                                print(f"  {s}")
                        else:
                            print(f"  {output_lines[-1] if output_lines else 'ok'}")
                except subprocess.TimeoutExpired:
                    print(f"[ERROR] {task_name} 超时 (120s)")
                except Exception as e:
                    print(f"[ERROR] {task_name} 执行失败: {e}")
        
        # 每秒检查一次
        time.sleep(30)

if __name__ == "__main__":
    main()
