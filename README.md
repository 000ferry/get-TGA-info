# TGA 余额自动监控脚本

脚本文件：`tga_monitor.py`

## 实现内容

对应你的 3 个需求：

1. 每轮开始先访问页面：
   - `https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/operating-cash-balance`
   - 解析其中 `New Data Expected MM/DD/YYYY`（例如 `03/02/2026`）。

2. 到达预计更新日（按美国东部时区 `America/New_York`）后，每隔 1 小时检查一次：
   - 从 Treasury API 拉取最新记录（含 `record_date` 与余额字段 `open_today_bal`）。
   - 若发现是新报表：
     - 提取余额数值（如 `$849,449` -> `849449`）。
     - 按 `新值/旧值 - 1` 计算涨幅。
     - 发送到 `1234567890@126.com`（默认收件人，可由环境变量覆盖）。
     - 邮件正文格式示例：
       - `（02/26/2026，TGA余额$849,449，涨幅1.25%，下次更新日期预计为03/02/2026）`

3. 成功发送后，重新进入下一轮：
   - 再次读取页面上的 `New Data Expected`。
   - 到下个预计更新日继续按小时轮询。

## 运行方式

给SMTP的user，授权码password，目标收件人设置好即可，命令文件txt可查看日志操作
python3 tga_monitor.py
```

## 状态文件

脚本会在当前目录生成 `tga_state.json`，用于保存：
- `last_record_date`
- `last_balance`

用于下次计算涨幅与判断是否是新报表。
