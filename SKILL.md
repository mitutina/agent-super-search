# Agent-Search v6.8

Hỏi nhiều web AI song song (ChatGPT, Gemini, DeepSeek, Qwen) qua `manager.py` rồi gom kết quả vào một file.

**Yêu cầu hệ thống:**
- Windows hoặc Linux có GUI (màn hình thật)
- KHÔNG hỗ trợ headless server, VPS không GUI

---

## 🖥️ LƯU Ý HỆ ĐIỀU HÀNH

**Lần đầu sử dụng trên bất kỳ hệ điều hành nào:** đọc `readme-for-new-setup.md` để setup (cài Python, Chrome, dependencies, tạo session). Mỗi hệ có hướng dẫn riêng trong file đó.

- **Windows native hoặc Linux native có GUI** → sau khi setup, dùng bình thường theo hướng dẫn bên dưới.
- **WSL (Windows Subsystem for Linux)**:
  - Setup sẽ move toàn bộ skill sang `C:\agent-super-search\` trên Windows. Thư mục WSL chỉ giữ lại 1 file `SKILL.md` redirect trỏ về đó.
  - Sau khi setup: mọi thao tác dùng skill tại `C:\agent-super-search\` qua Windows Python (không dùng python3 của WSL).

---

## 🚨 QUY TẮC TỐI THƯỢNG

**TUYỆT ĐỐI KHÔNG chạy `manager.py` với query ngắn, thiếu ngữ cảnh.**

Web AI chỉ thấy đúng chuỗi query bạn truyền — không đọc được lịch sử chat.
Hỏi cụt lủn = kết quả vô dụng.

**MẪU QUERY BẮT BUỘC** (điền những gì có, bỏ dòng không có):

```text
Context: [hệ thống, môi trường, stack, phiên bản]
Problem: [vấn đề cụ thể hoặc lỗi đang gặp]
Tried: [những gì đã thử và kết quả]
Current state: [đang bị kẹt ở đâu]
Question: [điều cụ thể cần web AI trả lời]
Goal: [kết quả mong đợi]
```

**Vi phạm = skill vô dụng.**

---

## 🖥️ CHẠY THEO NỀN TẢNG

### Windows

```bash
python manager.py "query của bạn" 1
python manager.py "query của bạn" 0
```

- `1` = hiện log chi tiết
- `0` = im lặng, chỉ in kết quả cuối

### Linux

```bash
python3 manager.py "query của bạn" 1
python3 manager.py "query của bạn" 0
```

### WSL (Windows Subsystem for Linux)

**⚠️ QUAN TRỌNG:** Skill này đã được move sang Windows tại `C:\agent-super-search\`.
Mọi lệnh phải chạy qua **PowerShell** (hoặc **CMD**) của Windows, không chạy từ WSL bash.

**Lần đầu sử dụng:** Đọc `readme-for-new-setup.md` để setup (move skill sang Windows, cài dep, tạo session).

**Chạy manager.py (từ WSL, qua PowerShell):**

```bash
# Đường dẫn tuyệt đối (theo pattern runAdmin)
POWERSHELL="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"

# Chạy với log chi tiết:
$POWERSHELL -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python manager.py 'query của bạn' 1"

# Chạy im lặng:
$POWERSHELL -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python manager.py 'query của bạn' 0"
```

> ❗ **Tại sao dùng PowerShell:** Query trong `'single quotes'` của PowerShell không bị parse sai dù có dấu ngoặc đơn `( )`. Đồng thời `Set-Location` đảm bảo Python thấy Windows path `C:\agent-super-search\...` → Chrome nhận đúng path. Tránh được cả 2 lỗi: cmd.exe escaping và WSL path `/mnt/c/...`.

**Sửa login/captcha (từ WSL, qua PowerShell hoặc CMD):**

```bash
# Qua PowerShell:
$POWERSHELL -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python fix-error.py chatgpt"
# hoặc: gemini, deepseek, qwen, all

# Qua CMD (nếu cần):
/mnt/c/Windows/System32/cmd.exe /c "cd /d C:\agent-super-search && python fix-error.py chatgpt"
```

**💡 GHI CHÚ CHO AGENT:**
- **Chạy manager.py:** Dùng PowerShell từ WSL như trên — query trong `'single quotes'`, không bị lỗi escaping
- **Đọc kết quả:** `cat /mnt/c/agent-super-search/output/result_*.txt` (WSL bash đọc file Windows bình thường)
- **Sửa login:** PowerShell hoặc CMD, luôn `Set-Location` / `cd /d` tới `C:\agent-super-search` để Chrome nhận đúng path
- **Không chạy trực tiếp python từ WSL bash** — sẽ gặp lỗi WSL path `/mnt/c/...` và cmd.exe escaping `( )`
- Tất cả file nằm trong `C:\agent-super-search\` (truy cập từ WSL qua `/mnt/c/agent-super-search/`)
- Nếu chưa setup, đọc `readme-for-new-setup.md` trước

---

## 🔧 FIX LOGIN / CAPTCHA / SESSION

Khi worker lỗi login, captcha, hoặc session expired.

### Windows

```bash
python fix-error.py chatgpt    # hoặc: gemini, deepseek, qwen, all
```

### Linux

**⚠️ QUAN TRỌNG:** Dùng `nohup` để browser không bị kill khi lệnh kết thúc.

```bash
# Mở 1 worker cụ thể:
nohup google-chrome --user-data-dir="$PWD/profiles/chatgpt" --profile-directory=Default --no-first-run --start-maximized https://chatgpt.com/ > /dev/null 2>&1 &

# Mở tất cả 4 workers (máy mới / đăng nhập lại hết):
nohup google-chrome --user-data-dir="$PWD/profiles/chatgpt" --profile-directory=Default --no-first-run --start-maximized https://chatgpt.com/ > /dev/null 2>&1 &
nohup google-chrome --user-data-dir="$PWD/profiles/gemini" --profile-directory=Default --no-first-run --start-maximized https://gemini.google.com/app > /dev/null 2>&1 &
nohup google-chrome --user-data-dir="$PWD/profiles/deepseek" --profile-directory=Default --no-first-run --start-maximized https://chat.deepseek.com/ > /dev/null 2>&1 &
nohup google-chrome --user-data-dir="$PWD/profiles/qwen" --profile-directory=Default --no-first-run --start-maximized https://chat.qwen.ai/ > /dev/null 2>&1 &
```

### WSL

```bash
# Dùng PowerShell từ WSL (không chạy trực tiếp python WSL bash):
POWERSHELL="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
$POWERSHELL -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python fix-error.py chatgpt"
# hoặc: gemini, deepseek, qwen, all
```

### Quy tắc fix

- `all` = máy mới hoặc cần đăng nhập lại nhiều worker cùng lúc
- `chatgpt|gemini|deepseek|qwen` = chỉ 1 worker bị lỗi
- User tự đăng nhập xong → tự đóng browser
- Agent chỉ chạy fix khi user đã đồng ý

---

## ✅ PREFLIGHT CHECK

Trước khi chạy, check nhanh:

1. [ ] Desktop đang mở, browser có thể hiện cửa sổ thật
2. [ ] Python chạy được (Windows: `python`, Linux: `python3`)
3. [ ] Chrome hoặc Chromium cài đặt
4. [ ] Thư mục skill có đủ: `manager.py`, `fix-error.py`, `search_*.py`
5. [ ] Có `profiles/` folder (nếu chưa có → chạy `fix-error.py` để tạo)

Nếu thiếu → dừng và setup trước (xem `readme-for-new-setup.md`).

---

## 📁 ĐƯỜNG DẪN VÀ PROFILE

**Không hard-code path tuyệt đối trong code.**

- `profiles/` → nằm cùng thư mục với worker
- `output/` → nằm cùng thư mục với worker
- `storage_state` → tự động tạo trong `profiles/`

**Lợi ích:** Copy cả folder sang chỗ khác → path tự đi theo, không cần sửa code.

---

## 📖 ĐỌC KẾT QUẢ VÀ TRẢ LỜI USER

Sau khi `manager.py` chạy xong, đọc file: `output/result_<timestamp>.txt`

**KHÔNG được nói chung chung** "mình đã hỏi 4 AI". Phải tổng hợp theo khung:

```text
Tóm tắt chi tiết

Quan điểm từng AI
- ChatGPT: ...
- Gemini: ...
- DeepSeek: ...
- Qwen: ...

Link dẫn chứng (nếu có)
- URL 1
- URL 2

Điểm chung giữa các AI

Đánh giá của Agent
- AI nào đáng tin hơn, vì sao
- AI nào suy đoán/thiếu căn cứ

Đề xuất của Agent sau khi tổng hợp

Kiểm tra lỗi worker
- Worker nào thành công
- Worker nào lỗi (login/captcha/session/timeout)
```

**Nếu có xung đột giữa các AI:**
- Chỉ ra chỗ mâu thuẫn
- Ưu tiên ý nào có dẫn chứng, lý lẽ cụ thể
- Không giả vờ tất cả đều đồng ý

**Nếu có worker lỗi:**
- Vẫn trả lời dựa trên worker chạy được
- Nói rõ worker nào lỗi, lỗi gì
- Đề xuất fix, không tự chạy nếu user chưa đồng ý

---

## 🏗️ KIẾN TRÚC

Mỗi file chạy độc lập:

| File | Chức năng |
|------|-----------|
| `manager.py` | Điều phối 4 workers + tổng hợp kết quả |
| `fix-error.py` | Mở browser với đúng profile để user sửa login |
| `search_chatgpt.py` | Worker ChatGPT (tự launch, tự save session) |
| `search_gemini.py` | Worker Gemini |
| `search_deepseek.py` | Worker DeepSeek |
| `search_qwen.py` | Worker Qwen |

**Lý do thiết kế:**
- Tránh một lõi hỏng → toàn bộ worker hỏng
- Dễ debug từng engine riêng
- Luồng login thủ công ổn định hơn (Google OAuth, captcha)

---

## 📦 NẾU DÙNG `.venv`

Mặc định chạy bằng Python hệ thống.

Nếu muốn dùng `.venv`:
1. Tự tạo `.venv` trong thư mục skill
2. Tự cài dependency: `pip install -r requirements.txt`
3. Tự dùng interpreter của `.venv` cho mọi lệnh
4. Ghi chú rõ: skill này chạy bằng `.venv`, không phải system Python

---

## ⚠️ LƯU Ý QUAN TRỌNG

1. **Application Visibility:** Browser phải hiển thị cửa sổ thật (không headless) để user theo dõi và sửa kịp thời.

2. **Không tự chạy fix:** Agent chỉ chạy `fix-error.py` khi user đã đồng ý.

3. **Worker fail = lỗi:** Bất kỳ worker nào không trả kết quả → xem là lỗi, báo rõ cho user.

4. **Profile bundling:** Profile nằm cùng thư mục worker → dễ mang đi, không phụ thuộc path tuyệt đối.

5. **WSL limitation:** Nếu chạy từ WSL, PHẢI gọi Python/Chrome của Windows. Không dùng python3 của WSL.
