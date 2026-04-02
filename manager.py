"""
Manager Script - Điều phối 4 AI workers song song.

Usage:
    python manager.py "<câu hỏi>" [log_flag]
    python manager.py "<câu hỏi>" [timestamp] [log_flag]
    python manager.py --setup [log_flag]
"""

import io
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import contextlib
import io
import json
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path


DEFAULT_BROWSER_ARGS = [
    "--start-maximized",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--no-first-run",
    "--profile-directory=Default",
    "--disable-gpu",
]

MANUAL_SETUP_BROWSER_ARGS = [
    "--start-maximized",
    "--no-first-run",
]

MANUAL_SESSION_AUTOSAVE_INTERVAL = 2


def configure_console():
    """Best-effort UTF-8 console cho Windows/Linux."""
    try:
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        if hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass


def parse_log_flag(value: str) -> bool:
    if value not in {"0", "1"}:
        raise ValueError("log_flag phải là '0' hoặc '1'")
    return value == "1"


def parse_worker_args(argv, script_name: str):
    """Parse args: query [timestamp|log_flag] [log_flag] or --setup [log_flag]."""
    if len(argv) < 2:
        raise ValueError(f'Usage: python {script_name} "<câu hỏi>" [timestamp] [log_flag]')

    command = argv[1]
    if command in {"--setup", "setup"}:
        log_enabled = True
        if len(argv) >= 3:
            log_enabled = parse_log_flag(argv[2])
        if len(argv) > 3:
            raise ValueError(f"Usage: python {script_name} --setup [log_flag]")
        return {
            "mode": "setup",
            "query": None,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "log_enabled": log_enabled,
        }

    query = command
    timestamp = None
    log_enabled = True

    if len(argv) >= 3:
        third_arg = argv[2]
        if third_arg in {"0", "1"} and len(argv) == 3:
            log_enabled = parse_log_flag(third_arg)
        else:
            timestamp = third_arg

    if len(argv) >= 4:
        log_enabled = parse_log_flag(argv[3])

    if len(argv) > 4:
        raise ValueError(f'Usage: python {script_name} "<câu hỏi>" [timestamp] [log_flag]')

    if timestamp is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    return {
        "mode": "run",
        "query": query,
        "timestamp": timestamp,
        "log_enabled": log_enabled,
    }


def build_stdout_context(log_enabled: bool):
    if log_enabled:
        return contextlib.nullcontext()
    return contextlib.redirect_stdout(io.StringIO())


def ensure_dirs(*dirs: Path):
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)


def resolve_profile_dir(base_dir: Path, primary_name: str, legacy_names=None) -> Path:
    profiles_dir = base_dir / "profiles"
    primary_path = profiles_dir / primary_name
    if primary_path.exists():
        return primary_path

    for legacy_name in legacy_names or []:
        legacy_path = profiles_dir / legacy_name
        if legacy_path.exists():
            return legacy_path

    return primary_path


def clear_profile_lock(profile_path: Path):
    lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie", "LOCK"]
    for file_name in lock_files:
        lock_file = profile_path / file_name
        if lock_file.exists():
            try:
                lock_file.unlink()
            except Exception:
                pass


def load_storage_state(context, state_path: Path):
    if not state_path.exists():
        return
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return

    cookies = data.get("cookies", [])
    if cookies:
        try:
            context.add_cookies(cookies)
        except Exception:
            pass

    origins = data.get("origins", [])
    for origin in origins:
        url = origin.get("origin")
        items = origin.get("localStorage", [])
        if not url or not items:
            continue
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.evaluate(
                """(entries) => {
                    for (const entry of entries) {
                        localStorage.setItem(entry.name, entry.value);
                    }
                }""",
                items,
            )
        except Exception:
            pass
        finally:
            try:
                page.close()
            except Exception:
                pass


def save_storage_state(context, state_path: Path, engine: str):
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
        print(f"[{engine}] ✓ Đã lưu storage_state: {state_path}")
    except Exception as exc:
        print(f"[{engine}] ✗ Lưu storage_state thất bại: {exc}")


def save_storage_state_quietly(context, state_path: Path):
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
    except Exception:
        pass


def add_stealth_script(context):
    context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        """
    )


def _candidate_browser_refs():
    env_exec = os.environ.get("AGENT_SEARCH_BROWSER_EXECUTABLE")
    if env_exec:
        env_path = Path(env_exec)
        if env_path.exists():
            yield {"executable_path": str(env_path)}, f"executable:{env_path}"

    system = platform.system()
    candidates = []
    if system == "Windows":
        candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
        ]
    elif system == "Linux":
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/snap/bin/chromium"),
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]

    for candidate in candidates:
        if candidate.exists():
            yield {"executable_path": str(candidate)}, f"executable:{candidate}"

    channel = os.environ.get("AGENT_SEARCH_BROWSER_CHANNEL", "chrome")
    if channel:
        yield {"channel": channel}, f"channel:{channel}"

    yield {}, "playwright-default"


def launch_persistent_context(
    playwright,
    profile_dir: Path,
    engine: str,
    storage_state_path: Path = None,
    timeout: int = 30000,
    extra_args=None,
    load_saved_state: bool = True,
    apply_stealth: bool = True,
):
    ensure_dirs(profile_dir)
    clear_profile_lock(profile_dir)
    args = list(DEFAULT_BROWSER_ARGS)
    if extra_args:
        args = list(extra_args)

    last_error = None
    for browser_ref, browser_label in _candidate_browser_refs():
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                args=args,
                timeout=timeout,
                **browser_ref,
            )
            if apply_stealth:
                add_stealth_script(context)
            if storage_state_path is not None and load_saved_state:
                load_storage_state(context, storage_state_path)
            print(f"[{engine}] ✓ Browser ready ({browser_label})")
            return context
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Không khởi động được browser cho {engine}: {last_error}")


def launch_browser(playwright, engine: str, timeout: int = 30000, extra_args=None):
    args = list(DEFAULT_BROWSER_ARGS)
    if extra_args:
        args.extend(extra_args)

    last_error = None
    for browser_ref, browser_label in _candidate_browser_refs():
        try:
            browser = playwright.chromium.launch(
                headless=False,
                args=args,
                timeout=timeout,
                **browser_ref,
            )
            print(f"[{engine}] ✓ Browser ready ({browser_label})")
            return browser
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Không khởi động được browser cho {engine}: {last_error}")


def detect_page_blockers(page, login_keywords=None, captcha_keywords=None, logout_keywords=None):
    payload = {
        "login_keywords": [k.lower() for k in (login_keywords or [])],
        "captcha_keywords": [k.lower() for k in (captcha_keywords or [])],
        "logout_keywords": [k.lower() for k in (logout_keywords or [])],
    }
    return page.evaluate(
        """(payload) => {
            const bodyText = (document.body.innerText || '').toLowerCase();
            const interactiveText = Array.from(document.querySelectorAll('button, a'))
                .map((el) => (el.innerText || '').toLowerCase().trim())
                .filter(Boolean)
                .join(' | ');

            const includesAny = (haystack, needles) => needles.some((needle) => haystack.includes(needle));

            return {
                hasCaptcha: includesAny(bodyText, payload.captcha_keywords),
                hasLoginPrompt: includesAny(bodyText, payload.login_keywords) || includesAny(interactiveText, payload.login_keywords),
                hasLogoutMarker: includesAny(bodyText, payload.logout_keywords),
            };
        }""",
        payload,
    )


def write_temp_file(temp_dir: Path, temp_prefix: str, engine: str, timestamp: str, result: dict):
    ensure_dirs(temp_dir)
    temp_file = temp_dir / f"{temp_prefix}_{timestamp}.txt"
    with open(temp_file, "w", encoding="utf-8") as handle:
        handle.write(f"[{engine}]\n")
        handle.write(f"Trạng thái: {'Thành công' if result['success'] else 'Thất bại'}\n")
        handle.write(f"Thời gian: {result['time']:.1f}s\n")
        handle.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        if result.get("data"):
            handle.write(f"\nKết quả:\n{result['data']}\n")
        else:
            handle.write(f"\nLỗi: {result.get('error')}\n")
    return temp_file


def finalize_worker_run(engine: str, temp_dir: Path, temp_prefix: str, timestamp: str, result: dict, log_enabled: bool):
    temp_file = write_temp_file(temp_dir, temp_prefix, engine, timestamp, result)
    if log_enabled:
        print(f"[{engine}] ✓ Đã lưu temp: {temp_file}")
        print(f"[{engine}] ✓ Hoàn thành ({result['time']:.1f}s)")
    else:
        if result.get("data"):
            print(result["data"])
        elif result.get("error"):
            print(f"[{engine}] {result['error']}")
    return temp_file


def wait_for_manual_browser_close(opened_contexts, intro_lines=None, skip_autosave_url_keywords=None):
    active = {
        item["key"]: {
            "label": item["label"],
            "context": item["context"],
            "state_path": item["state_path"],
            "last_save": 0.0,
        }
        for item in opened_contexts
    }

    if intro_lines:
        for line in intro_lines:
            print(line)

    skip_keywords = [keyword.lower() for keyword in (skip_autosave_url_keywords or [])]

    while active:
        now = time.time()
        closed_keys = []

        for key, item in active.items():
            context = item["context"]
            try:
                pages = context.pages
                should_skip_autosave = False
                if skip_keywords:
                    for page in pages:
                        try:
                            url = (page.url or "").lower()
                        except Exception:
                            url = ""
                        if any(keyword in url for keyword in skip_keywords):
                            should_skip_autosave = True
                            break

                if (not should_skip_autosave) and (now - item["last_save"] >= MANUAL_SESSION_AUTOSAVE_INTERVAL):
                    save_storage_state_quietly(context, item["state_path"])
                    item["last_save"] = now
            except Exception:
                closed_keys.append(key)

        for key in closed_keys:
            active.pop(key, None)

        if active:
            time.sleep(1)


def interactive_profile_setup(playwright, engine: str, profile_dir: Path, storage_state_path: Path, start_url: str, timeout: int = 30000):
    ensure_dirs(profile_dir, storage_state_path.parent)
    context = launch_persistent_context(
        playwright,
        profile_dir=profile_dir,
        engine=engine,
        storage_state_path=storage_state_path,
        timeout=timeout,
        extra_args=MANUAL_SETUP_BROWSER_ARGS,
        load_saved_state=False,
        apply_stealth=False,
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(timeout)
    page.goto(start_url, wait_until="domcontentloaded")
    page.bring_to_front()
    print(f"[{engine}] Đã mở trang setup: {start_url}")
    print(f"[{engine}] Hãy đăng nhập/tắt popup cần thiết trong cửa sổ browser này.")
    print(f"[{engine}] Không cần nhấn Enter trong terminal.")
    print(f"[{engine}] Khi đăng nhập xong, chờ 2-3 giây rồi tự đóng cửa sổ browser này.")
    wait_for_manual_browser_close(
        [
            {
                "key": engine.lower(),
                "label": engine,
                "context": context,
                "state_path": storage_state_path,
            }
        ],
        intro_lines=[
            f"[{engine}] Script sẽ giữ browser mở cho tới khi user tự đóng.",
            f"[{engine}] Session sẽ được autosave định kỳ trong lúc browser đang mở.",
        ],
        skip_autosave_url_keywords=[
            "accounts.google.com",
            "signin",
            "oauth",
            "myaccount.google.com",
        ],
    )
    print(f"[{engine}] ✓ Hoàn tất setup profile.")



configure_console()

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = OUTPUT_DIR / "temp"
FIX_SCRIPT = BASE_DIR / "fix-error.py"

WORKER_TIMEOUT = 600

WORKERS = [
    {
        "name": "ChatGPT",
        "script": "search_chatgpt.py",
        "temp_prefix": "chatgpt",
        "fix_target": "chatgpt",
        "profile_dir": BASE_DIR / "profiles" / "chatgpt",
        "url": "https://chatgpt.com/",
    },
    {
        "name": "Gemini",
        "script": "search_gemini.py",
        "temp_prefix": "gemini",
        "fix_target": "gemini",
        "profile_dir": BASE_DIR / "profiles" / "gemini",
        "url": "https://gemini.google.com/app",
    },
    {
        "name": "DeepSeek",
        "script": "search_deepseek.py",
        "temp_prefix": "deepseek",
        "fix_target": "deepseek",
        "profile_dir": BASE_DIR / "profiles" / "deepseek",
        "url": "https://chat.deepseek.com/",
    },
    {
        "name": "Qwen",
        "script": "search_qwen.py",
        "temp_prefix": "qwen",
        "fix_target": "qwen",
        "profile_dir": resolve_profile_dir(BASE_DIR, "qwen", legacy_names=["Qwen"]),
        "url": "https://chat.qwen.ai/",
    },
]


def parse_manager_args(argv):
    if len(argv) < 2:
        raise ValueError('Usage: python manager.py "<câu hỏi>" [timestamp] [log_flag] | --setup [log_flag]')

    command = argv[1]
    if command in {"--setup", "setup"}:
        log_enabled = True
        if len(argv) >= 3:
            log_enabled = parse_log_flag(argv[2])
        if len(argv) > 3:
            raise ValueError("Usage: python manager.py --setup [log_flag]")
        return {
            "mode": "setup",
            "query": None,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "log_enabled": log_enabled,
        }

    query = command
    timestamp = None
    log_enabled = True

    if len(argv) >= 3:
        third_arg = argv[2]
        if third_arg in {"0", "1"} and len(argv) == 3:
            log_enabled = parse_log_flag(third_arg)
        else:
            timestamp = third_arg

    if len(argv) >= 4:
        log_enabled = parse_log_flag(argv[3])

    if len(argv) > 4:
        raise ValueError('Usage: python manager.py "<câu hỏi>" [timestamp] [log_flag] | --setup [log_flag]')

    if timestamp is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    return {
        "mode": "run",
        "query": query,
        "timestamp": timestamp,
        "log_enabled": log_enabled,
    }


def find_browser_executable() -> str:
    env_exec = os.environ.get("AGENT_SEARCH_BROWSER_EXECUTABLE")
    if env_exec:
        env_path = Path(env_exec)
        if env_path.exists():
            return str(env_path)

    system = platform.system()
    candidates = []
    if system == "Windows":
        candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
        ]
    elif system == "Linux":
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/snap/bin/chromium"),
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise RuntimeError(
        "Không tìm thấy Chrome/Chromium. Hãy cài Chrome hoặc set AGENT_SEARCH_BROWSER_EXECUTABLE."
    )


def open_profile_browser(worker):
    browser_path = find_browser_executable()
    profile_dir = worker["profile_dir"]
    ensure_dirs(profile_dir)
    clear_profile_lock(profile_dir)

    cmd = [
        browser_path,
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--start-maximized",
        "--new-window",
        worker["url"],
    ]
    subprocess.Popen(cmd, cwd=str(BASE_DIR))


def run_setup(log_enabled: bool):
    if log_enabled:
        print("=" * 80)
        print("AGENT-SEARCH SETUP REDIRECT")
        print("=" * 80)
        print("Để tránh loãng lệnh, setup/login giờ dùng chung một flow duy nhất.")
        print("Manager sẽ gọi thẳng: fix-error.py all")
        print("=" * 80)

    cmd = [sys.executable, str(FIX_SCRIPT), "all"]
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        raise RuntimeError(f"Không mở được fix-error.py all (exit code {result.returncode})")

    if log_enabled:
        print("\n[MANAGER] ✓ Đã redirect sang fix-error.py all.")


def run_worker(worker_info, query, timestamp, log_enabled, status_map, lock):
    name = worker_info["name"]
    script_path = BASE_DIR / worker_info["script"]
    cmd = [sys.executable, str(script_path), query, timestamp, "1" if log_enabled else "0"]

    record = {
        "name": name,
        "script": str(script_path),
        "returncode": None,
        "ok": False,
        "timed_out": False,
        "stdout": "",
        "error": None,
    }

    if not script_path.exists():
        record["error"] = f"Không tìm thấy script: {script_path.name}"
        with lock:
            status_map[name] = record
        return

    try:
        syntax_check = subprocess.run(
            [sys.executable, "-m", "py_compile", str(script_path)],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
        )
        if syntax_check.returncode != 0:
            record["error"] = f"Syntax error:\n{syntax_check.stderr.strip()}"
            with lock:
                status_map[name] = record
            return

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            cwd=str(BASE_DIR),
        )

        try:
            stdout, _ = process.communicate(timeout=WORKER_TIMEOUT)
        except subprocess.TimeoutExpired:
            record["timed_out"] = True
            process.terminate()
            try:
                stdout, _ = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, _ = process.communicate()
            record["error"] = f"Timeout sau {WORKER_TIMEOUT}s"
        else:
            record["returncode"] = process.returncode
            record["ok"] = process.returncode == 0

        record["stdout"] = (stdout or "").strip()
        if record["returncode"] is None:
            record["returncode"] = process.returncode
            record["ok"] = process.returncode == 0

    except Exception as exc:
        record["error"] = str(exc)

    with lock:
        status_map[name] = record


def build_fix_command(target: str) -> str:
    return f'"{sys.executable}" "{FIX_SCRIPT}" {target}'


def classify_failure(worker, status) -> str:
    text = " ".join(
        [
            str(status.get("error") or ""),
            str(status.get("stdout") or ""),
        ]
    ).lower()

    login_keywords = [
        "chưa đăng nhập",
        "đăng nhập",
        "login",
        "log in",
        "sign in",
        "signed out",
        "captcha",
        "verify",
    ]

    if any(keyword in text for keyword in login_keywords):
        return (
            "Nghi lỗi session/login/captcha. "
            f"Nếu user muốn sửa ngay, mở profile này: {build_fix_command(worker['fix_target'])}"
        )

    if status.get("timed_out"):
        return (
            "Worker bị timeout. Nếu user muốn kiểm tra UI, mở profile này: "
            f"{build_fix_command(worker['fix_target'])}"
        )

    return f"Nếu user muốn kiểm tra thủ công, mở profile này bằng: {build_fix_command(worker['fix_target'])}"


def merge_results(query, timestamp, worker_status):
    ensure_dirs(OUTPUT_DIR, TEMP_DIR)
    result_file = OUTPUT_DIR / f"result_{timestamp}.txt"

    success_count = 0
    lines = []
    lines.append("=" * 80)
    lines.append("AI PARALLEL SEARCH RESULT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Câu hỏi: {query}")
    lines.append(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for worker in WORKERS:
        status = worker_status.get(worker["name"], {})
        if status.get("ok"):
            success_count += 1

    lines.append(f"Thành công: {success_count}/{len(WORKERS)} engines")
    lines.append("")
    lines.append("=" * 80)
    lines.append("")

    for worker in WORKERS:
        name = worker["name"]
        temp_file = TEMP_DIR / f"{worker['temp_prefix']}_{timestamp}.txt"
        status = worker_status.get(name, {})

        lines.append(f"[{name}]")
        lines.append("-" * 40)

        if temp_file.exists():
            try:
                lines.append(temp_file.read_text(encoding="utf-8").rstrip())
            except Exception as exc:
                lines.append(f"Lỗi đọc file temp: {exc}")
            if not status.get("ok"):
                lines.append("")
                lines.append(f"Nếu muốn sửa ngay: {classify_failure(worker, status)}")
        else:
            lines.append("Trạng thái: Thất bại")
            if status.get("timed_out"):
                lines.append(f"Lỗi: Timeout sau {WORKER_TIMEOUT}s")
            elif status.get("error"):
                lines.append(f"Lỗi: {status['error']}")
            elif status.get("returncode") is not None:
                lines.append(f"Lỗi: Worker exit code {status['returncode']}")
            else:
                lines.append("Lỗi: Worker không tạo được file temp")

            stdout = status.get("stdout", "").strip()
            if stdout:
                lines.append("")
                lines.append("Log cuối:")
                lines.extend(stdout.splitlines()[-20:])

            lines.append("")
            lines.append(f"Nếu muốn sửa ngay: {classify_failure(worker, status)}")

        lines.append("")
        lines.append("=" * 80)
        lines.append("")

    result_file.write_text("\n".join(lines), encoding="utf-8")
    return result_file


def print_summary(log_enabled: bool, query: str, timestamp: str, result_file: Path, worker_status):
    if log_enabled:
        print("\n" + "=" * 80)
        print("KẾT THÚC QUY TRÌNH")
        print("=" * 80)
        failed_workers = []
        for worker in WORKERS:
            status = worker_status.get(worker["name"], {})
            label = "OK" if status.get("ok") else "FAIL"
            reason = ""
            if status.get("timed_out"):
                reason = " (timeout)"
            elif status.get("error"):
                reason = f" ({status['error']})"
            elif status.get("returncode") not in (None, 0):
                reason = f" (exit code {status['returncode']})"
            print(f"{worker['name']}: {label}{reason}")
            if not status.get("ok"):
                failed_workers.append(worker)
        print(f"\nResult file: {result_file}")
        if failed_workers:
            print("\nWorker lỗi đã được ghi nhận.")
            print("Chỉ mở flow fix khi user thật sự muốn sửa ngay.")
            print("\nNếu cần mở profile để kiểm tra:")
            for worker in failed_workers:
                status = worker_status.get(worker["name"], {})
                print(f"- {worker['name']}: {classify_failure(worker, status)}")
            print(f'- Nếu user muốn mở tất cả profile: {build_fix_command("all")}')
        print("=" * 80)
    else:
        print(result_file.read_text(encoding="utf-8"))


def main():
    try:
        args = parse_manager_args(sys.argv)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)

    log_enabled = args["log_enabled"]

    if args["mode"] == "setup":
        run_setup(log_enabled)
        return

    query = args["query"]
    timestamp = args["timestamp"]

    ensure_dirs(OUTPUT_DIR, TEMP_DIR)

    if log_enabled:
        print("=" * 80)
        print("AI PARALLEL SEARCH MANAGER")
        print("=" * 80)
        print(f"Câu hỏi: {query}")
        print(f"Timestamp: {timestamp}")
        print("=" * 80)

    threads = []
    worker_status = {}
    lock = threading.Lock()

    for worker in WORKERS:
        thread = threading.Thread(
            target=run_worker,
            args=(worker, query, timestamp, log_enabled, worker_status, lock),
            daemon=True,
        )
        thread.start()
        threads.append((worker["name"], thread))
        if log_enabled:
            print(f"[MANAGER] Khởi động {worker['name']}...")

    for name, thread in threads:
        thread.join()
        status = worker_status.get(name, {})
        if log_enabled:
            print(f"[MANAGER] {name} xong: {'OK' if status.get('ok') else 'FAIL'}")
            stdout = status.get("stdout", "").strip()
            if stdout:
                for line in stdout.splitlines():
                    text = line.strip()
                    if text:
                        print(f"  [{name}] {text}")

    result_file = merge_results(query, timestamp, worker_status)
    print_summary(log_enabled, query, timestamp, result_file, worker_status)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[MANAGER] Người dùng hủy thao tác.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[MANAGER] Lỗi không mong muốn: {exc}")
        sys.exit(1)
