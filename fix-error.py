"""
Launch one or more worker setup processes for manual login/captcha/session repair.

Usage:
    python fix-error.py chatgpt
    python fix-error.py gemini
    python fix-error.py deepseek
    python fix-error.py qwen
    python fix-error.py all
"""

import subprocess
import sys
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

WORKERS = [
    {
        "key": "chatgpt",
        "label": "ChatGPT",
        "profile_dir": BASE_DIR / "profiles" / "chatgpt",
        "url": "https://chatgpt.com/",
    },
    {
        "key": "gemini",
        "label": "Gemini",
        "profile_dir": BASE_DIR / "profiles" / "gemini",
        "url": "https://gemini.google.com/app",
    },
    {
        "key": "deepseek",
        "label": "DeepSeek",
        "profile_dir": BASE_DIR / "profiles" / "deepseek",
        "url": "https://chat.deepseek.com/",
    },
    {
        "key": "qwen",
        "label": "Qwen",
        "profile_dir": resolve_profile_dir(BASE_DIR, "qwen", legacy_names=["Qwen"]),
        "url": "https://chat.qwen.ai/",
    },
]

WORKER_MAP = {worker["key"]: worker for worker in WORKERS}


def parse_args(argv):
    if len(argv) <= 1:
        raise ValueError("Usage: python fix-error.py [chatgpt|gemini|deepseek|qwen|all]")

    command = argv[1].strip().lower()
    valid = {"all"} | set(WORKER_MAP.keys())
    if command not in valid:
        raise ValueError(
            "Usage: python fix-error.py [chatgpt|gemini|deepseek|qwen|all]"
        )
    return command


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


def build_browser_command(worker):
    browser_path = find_browser_executable()
    profile_dir = worker["profile_dir"]
    ensure_dirs(profile_dir)
    clear_profile_lock(profile_dir)
    return [
        browser_path,
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--start-maximized",
        "--new-window",
        worker["url"],
    ]


def launch_worker_profile(worker):
    cmd = build_browser_command(worker)
    subprocess.Popen(cmd, cwd=str(BASE_DIR))
    print(f"[{worker['label']}] Đã mở Chrome thật với profile: {worker['profile_dir']}")


def run_fix(target):
    selected_workers = WORKERS if target == "all" else [WORKER_MAP[target]]

    print("Fix-error sẽ mở Chrome thật với đúng profile rồi thoát ngay.")
    print("Không dùng Playwright cho bước đăng nhập thủ công.")
    print("Khi sửa xong, user tự đóng các cửa sổ browser tương ứng.")
    print("")

    for index, worker in enumerate(selected_workers):
        launch_worker_profile(worker)
        if index < len(selected_workers) - 1:
            time.sleep(1)

    print("")
    print("✓ Đã mở xong các cửa sổ cần sửa lỗi.")
    print("✓ Lệnh này kết thúc ngay, không giữ vòng lặp chờ nữa.")


def main():
    try:
        target = parse_args(sys.argv)
        run_fix(target)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nNgười dùng đã hủy thao tác.")
        sys.exit(1)
    except EOFError:
        print("\nKhông nhận được input từ terminal.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nLỗi: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
