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

Mọi lệnh Python phải chạy bằng **Windows Python** (không dùng `python3` của WSL):

```bash
# Python Windows path (tìm trong quá trình setup, đường dẫn sau chỉ là ví dụ):
WIN_PYTHON="/mnt/c/Users/openclaw/AppData/Local/Programs/Python/Python313/python.exe"

# Chạy manager:
"$WIN_PYTHON" /mnt/c/agent-super-search/manager.py "query" 1

# Sửa login/captcha:
"$WIN_PYTHON" /mnt/c/agent-super-search/fix-error.py chatgpt

# Đọc kết quả:
cat /mnt/c/agent-super-search/output/result_*.txt
```

## Ghi chú

- `profiles/` và `output/` nằm trong `C:\agent-super-search\` trên Windows
- Browser chạy trên desktop Windows (có GUI thật)
- Không dùng `python3` của WSL cho skill này
- Khi cần sửa login: mở Chrome Windows với đúng profile trong `C:\agent-super-search\profiles\`
