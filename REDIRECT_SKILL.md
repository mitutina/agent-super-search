---
name: agent-super-search
description: Redirect — skill đã được move sang Windows để chạy browser automation với GUI thật. Agent: đọc C:\agent-super-search\SKILL.md để sử dụng.
---

# Agent Super Search — Redirect

Skill này đã được chuyển sang Windows tại `C:\agent-super-search\` để browser automation có GUI thật (WSL không có GUI nên không chạy trực tiếp được).

## Agent: Làm gì tiếp theo?

Đọc file SKILL.md trên Windows:

```
C:\agent-super-search\SKILL.md
```

Từ WSL, truy cập qua:
```
/mnt/c/agent-super-search/SKILL.md
```

## Chạy skill từ WSL

Mọi lệnh phải chạy qua **PowerShell** (không dùng WSL bash trực tiếp):

```bash
POWERSHELL="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"

# Chạy manager (query trong 'single quotes' của PowerShell, không bị lỗi escaping):
$POWERSHELL -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python manager.py 'query' 1"

# Sửa login/captcha:
$POWERSHELL -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python fix-error.py chatgpt"
# hoặc: gemini, deepseek, qwen, all

# Đọc kết quả (từ WSL bash):
cat /mnt/c/agent-super-search/output/result_*.txt
```

## Ghi chú

- `profiles/` và `output/` nằm trong `C:\agent-super-search\` trên Windows
- Browser chạy trên desktop Windows (có GUI thật)
- Không dùng `python3` của WSL cho skill này
- Không chạy trực tiếp python từ WSL bash — Chrome không hiểu WSL path `/mnt/c/...`
- Query có dấu ngoặc đơn `( )` dùng `'single quotes'` trong PowerShell, không bị parse sai