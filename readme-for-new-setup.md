# Agent-Search v6.8: New Machine Setup

File này là **entry point bắt buộc** khi skill được clone về máy mới hoặc chạy lần đầu.

Agent phải đọc file này trước khi làm bất kỳ thao tác nào với skill.

---

## 🖥️ CHỌN HỆ ĐIỀU HÀNH

Tùy theo hệ điều hành bạn đang chạy:

- **Windows native** → làm theo hướng dẫn [Windows](#-hướng-dẫn-cho-windows-native) bên dưới
- **Linux native** → làm theo hướng dẫn [Linux](#-hướng-dẫn-cho-linux-native) bên dưới
- **WSL (Windows Subsystem for Linux)** → làm theo hướng dẫn [WSL](#-hướng-dẫn-cho-wsl-đặc-biệt--phải-làm-đúng-trình-tự) bên dưới (QUAN TRỌNG: phải move skill sang Windows)

---

## 🪟 HƯỚNG DẪN CHO WINDOWS NATIVE

### 1. Check Python

```bash
python --version
```

Nếu chưa có:
```bash
winget install -e --id Python.Python.3.12
```

### 2. Check Chrome

```bash
where chrome
```

Nếu chưa có:
```bash
winget install -e --id Google.Chrome
```

### 3. Cài dependency

```bash
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### 4. Tạo session lần đầu

```bash
python fix-error.py all
```

4 cửa sổ Chrome sẽ mở ra (ChatGPT, Gemini, DeepSeek, Qwen).
**User phải tự đăng nhập vào từng cửa sổ**, xong thì đóng lại.

### 5. Smoke test

```bash
python manager.py "test" 1
```

### 6. Hoàn tất

Skill đã sẵn sàng. Dùng `SKILL.md` để biết cách chạy hàng ngày.

---

## 🐧 HƯỚNG DẪN CHO LINUX NATIVE

### 1. Check Python

```bash
python3 --version
```

Nếu chưa có (Ubuntu/Debian):
```bash
sudo apt update && sudo apt install -y python3 python3-pip
```

### 2. Check Chrome/Chromium

```bash
which google-chrome || which chromium || which chromium-browser
```

Nếu chưa có (Ubuntu/Debian):
```bash
sudo apt install -y google-chrome-stable
# hoặc
sudo apt install -y chromium-browser
```

### 3. Cài dependency

```bash
python3 -m pip install -U pip
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 -m playwright install-deps chromium
```

### 4. Tạo session lần đầu (DÙNG NOHUP, KHÔNG dùng fix-error.py)

⚠️ Trên Linux, `fix-error.py` sẽ bị kill browser khi process cha exit. Phải dùng `nohup`:

```bash
nohup google-chrome --user-data-dir="$PWD/profiles/chatgpt" --profile-directory=Default --no-first-run --start-maximized --disable-gpu --disable-webgl --disable-software-rasterizer https://chatgpt.com/ > /dev/null 2>&1 &
nohup google-chrome --user-data-dir="$PWD/profiles/gemini" --profile-directory=Default --no-first-run --start-maximized --disable-gpu --disable-webgl --disable-software-rasterizer https://gemini.google.com/app > /dev/null 2>&1 &
nohup google-chrome --user-data-dir="$PWD/profiles/deepseek" --profile-directory=Default --no-first-run --start-maximized --disable-gpu --disable-webgl --disable-software-rasterizer https://chat.deepseek.com/ > /dev/null 2>&1 &
nohup google-chrome --user-data-dir="$PWD/profiles/qwen" --profile-directory=Default --no-first-run --start-maximized --disable-gpu --disable-webgl --disable-software-rasterizer https://chat.qwen.ai/ > /dev/null 2>&1 &
```

User tự đăng nhập vào từng cửa sổ, xong thì đóng lại.

### 5. Smoke test

```bash
python3 manager.py "test" 1
```

### 6. Hoàn tất

Skill đã sẵn sàng. Dùng `SKILL.md` để biết cách chạy hàng ngày.

---

## 🔷 HƯỚNG DẪN CHO WSL (ĐẶC BIỆT — PHẢI LÀM ĐÚNG TRÌNH TỰ)

WSL không có GUI → browser không mở được từ WSL → worker sẽ chết nếu chạy Python của WSL.

**Giải pháp:** Move toàn bộ thư mục skill sang Windows (`C:\agent-super-search\`) và chạy mọi thứ bằng Python + Chrome của Windows qua PowerShell.

### Bước 1: Move thư mục skill sang Windows

Từ WSL, copy toàn bộ thư mục skill sang ổ C của Windows:

```bash
# Xác định đường dẫn nguồn (thư mục skill hiện tại)
SKILL_SRC="$(dirname "$(readlink -f "$0")")"
# Nếu $0 không hoạt động, dùng trực tiếp:
SKILL_SRC="/home/openclaw/.openclaw/workspace-mark6-code/skill/agent-super-search"

# Copy sang Windows qua /mnt/c
cp -r "$SKILL_SRC" /mnt/c/agent-super-search

# Fix permission cho Windows Python đọc được file
/mnt/c/Windows/System32/cmd.exe /c "icacls C:\agent-super-search\* /grant Everyone:F /T" 2>/dev/null

# Verify
ls /mnt/c/agent-super-search/manager.py && echo "✅ Move thành công" || echo "❌ Move thất bại"
```

### Bước 2: Tìm Windows Python path

```bash
# Tìm Python trên Windows
/mnt/c/Windows/System32/cmd.exe /c "where python" 2>/dev/null

# Hoặc tìm trong AppData:
ls /mnt/c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe 2>/dev/null

# Hoặc tìm trong Program Files:
ls /mnt/c/Program\ Files/Python3*/python.exe 2>/dev/null
```

**Agent phải ghi lại path tìm được.** Ví dụ:
```
WIN_PYTHON="/mnt/c/Users/openclaw/AppData/Local/Programs/Python/Python313/python.exe"
```

Nếu chưa có Python trên Windows, cài đặt:
1. Mở `cmd.exe` trên Windows (không phải WSL)
2. Chạy: `winget install -e --id Python.Python.3.12`
3. Hoặc tải từ https://python.org

### Bước 3: Cài dependency bằng Windows Python

```bash
# Dùng đường dẫn Python đã tìm được ở bước 2
WIN_PYTHON="/mnt/c/Users/openclaw/AppData/Local/Programs/Python/Python313/python.exe"

"$WIN_PYTHON" -m pip install -U pip
"$WIN_PYTHON" -m pip install -r /mnt/c/agent-super-search/requirements.txt || "$WIN_PYTHON" -m pip install playwright
"$WIN_PYTHON" -m playwright install chromium
```

### Bước 4: Tạo session lần đầu (qua PowerShell)

```bash
# Dùng PowerShell để Chrome nhận đúng Windows path (không chạy trực tiếp python từ WSL bash)
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python fix-error.py all"
```

4 cửa sổ Chrome Windows sẽ mở ra. **User phải tự đăng nhập** vào từng cửa sổ, xong thì đóng lại.

### Bước 5: Smoke test (qua PowerShell)

```bash
# Dùng PowerShell (tránh lỗi cmd.exe parse sai query có dấu ngoặc đơn)
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python manager.py 'test' 1"
```

### Bước 6: Tạo redirect SKILL.md và dọn dẹp WSL

Sau khi move thành công, thư mục skill trong WSL chỉ cần giữ 1 file `SKILL.md` redirect trỏ về Windows.
File `REDIRECT_SKILL.md` có sẵn template — agent copy nó thành `SKILL.md` rồi xóa các file còn lại:

```bash
cd "$SKILL_SRC"
cp REDIRECT_SKILL.md SKILL.md
rm -f README.md fix-error.py manager.py must-be.png readme-for-new-setup.md requirements.txt search_*.py vi-tri-web-search.png REDIRECT_SKILL.md
echo "✅ WSL dir cleaned, only SKILL.md remains"
```

### Bước 7: Hoàn tất

Skill đã sẵn sàng. Từ giờ agent dùng `/mnt/c/agent-super-search/SKILL.md` để tham khảo cách chạy hàng ngày.
WSL chỉ còn 1 file `SKILL.md` redirect — khi agent mở skill trong WSL, sẽ đọc redirect và biết phải sang Windows.

**Ghi chú cho agent sau setup:**
- Chạy manager.py qua PowerShell: `$POWERSHELL -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python manager.py 'query' 1"`
- Chạy fix-error.py qua PowerShell: `$POWERSHELL -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python fix-error.py chatgpt"`
- Đọc kết quả từ WSL bash: `cat /mnt/c/agent-super-search/output/result_*.txt`
- `profiles/` và `output/` nằm trong `C:\agent-super-search\` trên Windows
- Không chạy trực tiếp python từ WSL bash — Chrome không hiểu WSL path `/mnt/c/...`

---

## 🔄 KHI NÀO PHẢI CHẠY SETUP LẠI

- máy mới hoàn toàn
- `profiles/` chưa có
- session hết hạn
- worker báo chưa đăng nhập
- worker bị captcha và chưa lưu lại session mới
- user xóa profile hoặc storage state

---

## 🔧 SỬA LỖI LOGIN / CAPTCHA SAU NÀY

### Windows native
```bash
python fix-error.py chatgpt    # hoặc: gemini, deepseek, qwen, all
```

### Linux native (DÙNG NOHUP)
```bash
nohup google-chrome --user-data-dir="$PWD/profiles/chatgpt" --profile-directory=Default --no-first-run --start-maximized --disable-gpu https://chatgpt.com/ > /dev/null 2>&1 &
```

### WSL (qua PowerShell — không chạy trực tiếp python WSL bash)
```bash
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\agent-super-search'; python fix-error.py chatgpt"
# hoặc: gemini, deepseek, qwen, all
```

**Quy tắc chung:**
- `all` = máy mới hoặc cần đăng nhập lại nhiều worker
- `chatgpt|gemini|deepseek|qwen` = chỉ 1 worker bị lỗi
- User tự đăng nhập xong → tự đóng browser
- Agent chỉ chạy fix khi user đã đồng ý

---

## ✅ PREFLIGHT CHECK (cho mọi nền tảng)

Trước khi chạy skill, check nhanh:

1. [ ] Desktop đang mở, browser có thể hiện cửa sổ thật
2. [ ] Python chạy được (Windows: `python`, Linux: `python3`, WSL: Windows Python path)
3. [ ] Chrome hoặc Chromium cài đặt
4. [ ] Thư mục skill có đủ: `manager.py`, `fix-error.py`, `search_*.py`
5. [ ] Có `profiles/` folder (nếu chưa có → chạy bước tạo session)

Nếu thiếu → quay lại làm bước setup tương ứng với OS.

---

## 📋 TÓM TẮT NHANH CHO AGENT

### Nếu Windows native:
1. Check Python → check Chrome → cài dep → `fix-error.py all` → đăng nhập → smoke test

### Nếu Linux native:
1. Check python3 → check Chrome → cài dep → nohup mở 4 profile → đăng nhập → smoke test

### Nếu WSL:
1. **Move skill sang `C:\agent-super-search\`**
2. Tìm Windows Python path
3. Cài dep bằng Windows Python (từ WSL bash, bước này không cần PowerShell)
4. `fix-error.py all` qua PowerShell (để Chrome nhận đúng Windows path)
5. Đăng nhập từng profile (cửa sổ Chrome Windows)
6. Smoke test qua PowerShell: `python manager.py 'test' 1`
7. **Tạo redirect SKILL.md trong WSL**
8. Từ giờ chạy manager.py qua PowerShell, WSL bash chỉ để đọc output

---

## ⚠️ LƯU Ý QUAN TRỌNG

1. **WSL = không có GUI** — tuyệt đối không chạy Python của WSL cho skill này
2. **Linux = dùng nohup** — `fix-error.py` sẽ bị kill browser trên Linux
3. **Profile bundling** — profiles/output nằm cùng thư mục skill, không hard-code path
4. **Không tự chạy fix** — chỉ chạy `fix-error.py` khi user đồng ý
5. **GitHub** — không đẩy `profiles/`, `output/`, `__pycache__/` lên repo

---

## 📦 LƯU Ý GITHUB

Có thể đẩy folder skill lên GitHub, nhưng không nên đẩy:
- `profiles/`
- `output/`
- `__pycache__/`

`.gitignore` đã chặn các thư mục này.