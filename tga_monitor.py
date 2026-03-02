#!/usr/bin/env python3
"""TGA 余额监控器。

功能：
1. 读取 Daily Treasury Statement 页面中的 `New Data Expected` 日期。
2. 在预计更新日（美国东部时间）按小时轮询最新报表。
3. 检测到新值后，计算涨幅并发送邮件。
4. 发送后重新读取下一个预计更新日，循环执行。

依赖：仅使用 Python 标准库。
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any, Optional
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PAGE_URL = (
    "https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/"
    "operating-cash-balance"
)
API_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/"
    "accounting/dts/operating_cash_balance"
)
STATE_FILE = Path("tga_state.json")
EASTERN_TZ = ZoneInfo("America/New_York")


@dataclass
class TGARecord:
    record_date: str
    balance: int


def fetch_url_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_next_expected_date() -> str:
    html = fetch_url_text(PAGE_URL)
    match = re.search(r"New\s+Data\s+Expected\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", html, re.I)
    if not match:
        raise ValueError("页面中未找到 'New Data Expected MM/DD/YYYY'。")
    return match.group(1)


def fetch_latest_record() -> TGARecord:
    query = urlencode({"sort": "-record_date", "page[size]": 1})
    payload = fetch_url_text(f"{API_URL}?{query}")
    data = json.loads(payload).get("data", [])
    if not data:
        raise ValueError("API 返回为空，无法获取最新 TGA 数据。")

    row = data[0]
    record_date = row.get("record_date")
    raw_balance = row.get("open_today_bal")

    if not record_date or raw_balance is None:
        raise ValueError(f"API 字段缺失，收到数据：{row}")

    balance = int(float(str(raw_balance).replace(",", "")))
    return TGARecord(record_date=record_date, balance=balance)


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def calc_growth(new_value: int, old_value: Optional[int]) -> Optional[float]:
    if old_value is None or old_value == 0:
        return None
    return new_value / old_value - 1


def fmt_currency(value: int) -> str:
    return f"${value:,}"


def fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def send_email(
    to_email: str,
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("TGA Monitor", smtp_user))
    msg["To"] = to_email

    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [to_email], msg.as_string())


def parse_mmddyyyy(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%m/%d/%Y").replace(tzinfo=EASTERN_TZ)


def now_est() -> datetime:
    return datetime.now(EASTERN_TZ)


def sleep_to_next_hour_est() -> None:
    now = now_est()
    next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    seconds = max(1, int((next_hour - now).total_seconds()))
    time.sleep(seconds)


def build_mail_line(display_date: str, balance: int, growth: Optional[float], next_expected: str) -> str:
    return (
        f"（{display_date}，TGA余额{fmt_currency(balance)}，"
        f"涨幅{fmt_pct(growth)}，下次更新日期预计为{next_expected}）"
    )


def monitor() -> None:
    recipient = os.getenv("TGA_RECIPIENT", "abc244005@126.com")
    smtp_host = os.getenv("SMTP_HOST", "smtp.126.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        raise RuntimeError("请先设置 SMTP_USER 与 SMTP_PASSWORD 环境变量。")

    state = load_state()

    while True:
        next_expected = fetch_next_expected_date()
        print(f"[INFO] 当前页面预计下次更新时间: New Data Expected {next_expected}")

        expected_date = parse_mmddyyyy(next_expected).date()

        while now_est().date() < expected_date:
            print("[INFO] 未到预计更新日，休眠到下一个整点(EST)...")
            sleep_to_next_hour_est()

        print("[INFO] 已到预计更新日，开始每小时检测最新报表...")

        while True:
            latest = fetch_latest_record()
            last_record_date = state.get("last_record_date")

            if latest.record_date != last_record_date:
                old_balance = state.get("last_balance")
                growth = calc_growth(latest.balance, old_balance)

                body = build_mail_line(latest.record_date, latest.balance, growth, next_expected)
                send_email(
                    to_email=recipient,
                    subject="TGA 余额更新通知",
                    body=body,
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    smtp_user=smtp_user,
                    smtp_password=smtp_password,
                )

                state["last_record_date"] = latest.record_date
                state["last_balance"] = latest.balance
                save_state(state)

                print(f"[INFO] 检测到新报表并发送邮件: {body}")
                break

            print("[INFO] 暂无新报表，1小时后重试...")
            sleep_to_next_hour_est()


if __name__ == "__main__":
    while True:
        try:
            monitor()
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            print(f"[WARN] 网络或数据错误: {exc}; 5分钟后重试")
            time.sleep(300)
        except Exception as exc:
            print(f"[ERROR] 未预期错误: {exc}; 5分钟后重试")
            time.sleep(300)
