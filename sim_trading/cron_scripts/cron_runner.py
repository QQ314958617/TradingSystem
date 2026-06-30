#!/usr/bin/env python3
"""
Cron通用执行器 - 接受脚本名称作为参数，直接执行并处理输出/错误
用法: python3 cron_runner.py run_overnight_sell.py
"""
import subprocess
import sys
import os
from datetime import datetime

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = "/tmp/cron_logs"

def main():
    if len(sys.argv) < 2:
        print("Usage: cron_runner.py <script_name>")
        sys.exit(1)
    
    script_name = sys.argv[1]
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    
    if not os.path.exists(script_path):
        print(f"[ERROR] Script not found: {script_path}")
        sys.exit(1)
    
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"{script_name.replace('.py','')}_{timestamp}.log")
    
    print(f"[{timestamp}] Running: {script_name}", flush=True)
    print(f"  Script: {script_path}", flush=True)
    
    result = subprocess.run(
        ["python3", script_path],
        capture_output=True, text=True, timeout=120
    )
    
    # 写日志
    with open(log_file, "w") as f:
        f.write(f"[{timestamp}] STDOUT:\n")
        f.write(result.stdout)
        f.write(f"\n[{timestamp}] STDERR:\n")
        f.write(result.stderr)
        f.write(f"\n[{timestamp}] RC={result.returncode}\n")
    
    # 输出到stdout（会被cron capture）
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(f"[STDERR] {result.stderr[:200]}", end="", flush=True)
    
    print(f"\n[{datetime.now().strftime('%Y%m%d_%H%M%S')}] RC={result.returncode}", flush=True)
    
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
