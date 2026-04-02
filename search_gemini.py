"""
Search Gemini - Standalone Script
Fix: JavaScript syntax, text detection, auto-complete mechanism, model selection
Profile: profiles/gemini/
Output: output/gemini_result.txt
"""
import sys
import subprocess
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import contextlib
import io
import json
import os
import platform
import sys
import time
import urllib.request
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

    raise RuntimeError("Khong tim thay Chrome/Chromium.")


def is_cdp_endpoint_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for_cdp_endpoint(port: int, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Chrome CDP endpoint khong san sang o port {port}: {last_error}")


def launch_real_chrome_with_cdp(playwright, engine: str, profile_dir: Path, start_url: str, cdp_port: int, timeout: int = 30000):
    ensure_dirs(profile_dir)
    chrome_process = None
    endpoint = f"http://127.0.0.1:{cdp_port}"

    if not is_cdp_endpoint_ready(cdp_port):
        browser_path = find_browser_executable()
        clear_profile_lock(profile_dir)
        cmd = [
            browser_path,
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            "--start-maximized",
            f"--remote-debugging-port={cdp_port}",
            "--new-window",
            start_url,
        ]
        chrome_process = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait_for_cdp_endpoint(cdp_port, max(timeout / 1000.0, 15.0))

    browser = playwright.chromium.connect_over_cdp(endpoint)
    if not browser.contexts:
        raise RuntimeError(f"Khong attach duoc Chrome context cho {engine}")

    context = browser.contexts[0]
    page = context.pages[-1] if context.pages else context.new_page()
    print(f"[{engine}] Browser ready (real Chrome + CDP, port {cdp_port})")
    return browser, context, page, chrome_process


def close_attached_browser(browser, chrome_process):
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass

    if chrome_process is not None:
        try:
            chrome_process.wait(timeout=5)
        except Exception:
            try:
                chrome_process.terminate()
            except Exception:
                pass
            try:
                chrome_process.wait(timeout=5)
            except Exception:
                try:
                    chrome_process.kill()
                except Exception:
                    pass


def open_real_browser_for_setup(engine: str, profile_dir: Path, start_url: str):
    browser_path = find_browser_executable()
    ensure_dirs(profile_dir)
    clear_profile_lock(profile_dir)
    cmd = [
        browser_path,
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--start-maximized",
        "--new-window",
        start_url,
    ]
    subprocess.Popen(cmd, cwd=str(BASE_DIR))
    print(f"[{engine}] Da mo Chrome that voi profile: {profile_dir}")

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

# Cấu hình
BASE_DIR = Path(__file__).parent
PROFILE_DIR = BASE_DIR / "profiles" / "gemini"
STORAGE_STATE_PATH = BASE_DIR / "profiles" / "gemini_storage_state.json"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = OUTPUT_DIR / "temp"
TIMEOUT_MS = 60000
CDP_PORT = 9332


def select_model_with_fallback(page, engine, timestamp=None, output_dir=None):
    """Ưu tiên chọn model Tư duy (Thinking), fallback sang Nhanh (Fast)."""
    def open_model_menu():
        return page.evaluate(r"""
            () => {
                const normalize = (s) => (s || '')
                    .toLowerCase()
                    .normalize('NFD')
                    .replace(/[\u0300-\u036f]/g, '')
                    .replace(/đ/g, 'd')
                    .replace(/\s+/g, ' ')
                    .trim();

                const candidates = Array.from(document.querySelectorAll('button, div[role="button"], div[role="combobox"]'));
                let best = null;
                let bestScore = -1;

                for (const el of candidates) {
                    const rawText = (el.innerText || el.textContent || '');
                    const rawAria = (el.getAttribute('aria-label') || '');
                    const text = normalize(rawText);
                    const aria = normalize(rawAria);
                    const className = normalize(el.className || '');
                    const rect = el.getBoundingClientRect();

                    if (rect.width < 30 || rect.height < 16) continue;

                    let score = 0;
                    if (text.includes('nhanh') || text.includes('fast') || text.includes('quick')) score += 5;
                    if (text.includes('tu duy') || text.includes('thinking') || text.includes('deep think')) score += 6;
                    if (/\bpro\b/.test(text) || text.includes('flash')) score += 3;
                    if (text.includes('gemini 3') || text.includes('gemini 2')) score += 2;
                    if (aria.includes('model') || aria.includes('mo hinh')) score += 8;
                    if (
                        aria.includes('mo bo chon che do') ||
                        aria.includes('mode picker') ||
                        aria.includes('open mode picker') ||
                        aria.includes('open model picker') ||
                        aria.includes('mode switch')
                    ) score += 12;
                    if (el.getAttribute('aria-haspopup') === 'true') score += 4;
                    if (className.includes('input-area-switch')) score += 16;
                    if (el.querySelector('svg')) score += 1;

                    if (score > bestScore) {
                        bestScore = score;
                        best = el;
                    }
                }

                if (!best || bestScore < 4) {
                    return { ok: false, text: '', score: bestScore };
                }

                const chosenText = (best.innerText || best.textContent || '').replace(/\s+/g, ' ').trim();
                best.click();
                return { ok: true, text: chosenText.slice(0, 80), score: bestScore };
            }
        """)

    def collect_menu_info():
        return page.evaluate(r"""
            () => {
                const normalize = (s) => (s || '')
                    .toLowerCase()
                    .normalize('NFD')
                    .replace(/[\u0300-\u036f]/g, '')
                    .replace(/đ/g, 'd')
                    .replace(/\s+/g, ' ')
                    .trim();

                const items = Array.from(document.querySelectorAll('[role="option"], [role="menuitem"], [role="menuitemradio"], li, button, div'));
                const options = [];
                const seen = new Set();

                for (const el of items) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 40 || rect.height < 16) continue;

                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

                    const raw = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                    if (!raw || raw.length > 160) continue;

                    const text = normalize(raw);
                    if (!text) continue;

                    const likelyModelOption =
                        text.includes('tu duy') || text.includes('nhanh') || text.includes('thinking') ||
                        text.includes('fast') || text.includes('quick') || /\bpro\b/.test(text) ||
                        text.includes('flash') || text.includes('giai quyet cac van de phuc tap') ||
                        text.includes('tra loi nhanh') || text.includes('complex problem') ||
                        text.includes('problem solving') || text.includes('quick response') ||
                        text.includes('quick responses') || text.includes('quick answer') ||
                        text.includes('quick answers') || text.includes('gemini 3');

                    if (!likelyModelOption) continue;
                    if (seen.has(text)) continue;

                    seen.add(text);
                    options.push({ text: raw, normalized: text });
                }

                return { count: options.length, options };
            }
        """)

    def get_current_model_label():
        return page.evaluate(r"""
            () => {
                const normalize = (s) => (s || '')
                    .toLowerCase()
                    .normalize('NFD')
                    .replace(/[\u0300-\u036f]/g, '')
                    .replace(/đ/g, 'd')
                    .replace(/\s+/g, ' ')
                    .trim();

                const candidates = Array.from(document.querySelectorAll('button, div[role="button"], div[role="combobox"]'));
                let best = null;
                let bestScore = -1;

                for (const el of candidates) {
                    const rawText = (el.innerText || el.textContent || '');
                    const rawAria = (el.getAttribute('aria-label') || '');
                    const text = normalize(rawText);
                    const aria = normalize(rawAria);
                    const className = normalize(el.className || '');
                    const rect = el.getBoundingClientRect();

                    if (rect.width < 30 || rect.height < 16) continue;

                    let score = 0;
                    if (text.includes('nhanh') || text.includes('fast') || text.includes('quick')) score += 5;
                    if (text.includes('tu duy') || text.includes('thinking') || text.includes('deep think')) score += 6;
                    if (/\bpro\b/.test(text) || text.includes('flash')) score += 3;
                    if (
                        aria.includes('mo bo chon che do') ||
                        aria.includes('mode picker') ||
                        aria.includes('open mode picker') ||
                        aria.includes('open model picker') ||
                        aria.includes('mode switch')
                    ) score += 12;
                    if (className.includes('input-area-switch')) score += 16;

                    if (score > bestScore) {
                        bestScore = score;
                        best = el;
                    }
                }

                if (!best) {
                    return { text: '', normalized: '', score: bestScore };
                }

                const raw = (best.innerText || best.textContent || '').replace(/\s+/g, ' ').trim();
                return { text: raw.slice(0, 80), normalized: normalize(raw), score: bestScore };
            }
        """)

    def click_model_option(target):
        return page.evaluate(r"""
            (target) => {
                const normalize = (s) => (s || '')
                    .toLowerCase()
                    .normalize('NFD')
                    .replace(/[\u0300-\u036f]/g, '')
                    .replace(/đ/g, 'd')
                    .replace(/\s+/g, ' ')
                    .trim();

                const menu = document.querySelector('.gds-mode-switch-menu, [role="menu"]') || document;
                const nodes = Array.from(menu.querySelectorAll('.mode-option-wrapper, .title-and-check, .title-and-description, [role="option"], [role="menuitem"], [role="menuitemradio"], li, button, div'));

                const isVisible = (el) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 40 || rect.height < 16) return false;
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                };

                const clickElement = (el) => {
                    const targetNode =
                        el.querySelector('.title-and-check, .title-and-description, button, [role="menuitemradio"], [role="menuitem"], [role="option"]') ||
                        el;

                    targetNode.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const rect = targetNode.getBoundingClientRect();
                    const clientX = rect.left + rect.width / 2;
                    const clientY = rect.top + rect.height / 2;

                    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        targetNode.dispatchEvent(new MouseEvent(type, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX,
                            clientY
                        }));
                    }

                    if (typeof targetNode.click === 'function') {
                        targetNode.click();
                    }
                };

                let best = null;
                let bestScore = -1;

                for (const el of nodes) {
                    if (!isVisible(el)) continue;

                    const raw = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                    if (!raw || raw.length > 120) continue;

                    const text = normalize(raw);
                    if (!text) continue;

                    const hasThinking = text.includes('tu duy') || text.includes('thinking');
                    const hasFast = text.includes('nhanh') || text.includes('fast') || text.includes('quick');
                    const hasPro = /\bpro\b/.test(text);

                    if (target === 'thinking' && (!hasThinking || hasFast || hasPro)) continue;
                    if (target === 'fast' && (!hasFast || hasThinking || hasPro)) continue;

                    const className = normalize(el.className || '');
                    const role = normalize(el.getAttribute('role') || '');
                    let score = 0;

                    if (target === 'thinking') {
                        if (text.includes('tu duy') || text.includes('thinking')) score += 14;
                        if (text.includes('giai quyet cac van de phuc tap')) score += 8;
                        if (text.includes('complex problem')) score += 8;
                        if (text.includes('problem solving')) score += 6;
                        if (text.includes('reasoning')) score += 4;
                    } else {
                        if (text.includes('nhanh') || text.includes('fast')) score += 14;
                        if (text.includes('tra loi nhanh')) score += 8;
                        if (text.includes('quick response') || text.includes('quick responses')) score += 8;
                        if (text.includes('quick answer') || text.includes('quick answers')) score += 6;
                    }

                    if (className.includes('mode-option-wrapper')) score += 16;
                    if (className.includes('title-and-check')) score += 12;
                    if (className.includes('title-and-description')) score += 8;
                    if (role === 'option' || role === 'menuitem' || role === 'menuitemradio') score += 10;

                    if (score > bestScore) {
                        bestScore = score;
                        best = { element: el, raw };
                    }
                }

                if (!best || bestScore < 12) {
                    return { ok: false, model: '', score: bestScore };
                }

                clickElement(best.element);
                return { ok: true, model: best.raw.slice(0, 120), score: bestScore };
            }
        """, target)

    def ensure_model_menu_open():
        is_open = page.evaluate("""() => !!document.querySelector('.gds-mode-switch-menu, [role="menu"]')""")
        if is_open:
            return True

        reopen_result = open_model_menu()
        if not reopen_result.get("ok"):
            return False

        print(f"[{engine}] ↻ Mở lại menu model (button: '{reopen_result.get('text')}', score={reopen_result.get('score')})")
        page.wait_for_timeout(1200)
        return True

    def verify_model(expected):
        current = get_current_model_label()
        normalized = current.get("normalized", "")
        if expected == "thinking":
            ok = "tu duy" in normalized or "thinking" in normalized or "reasoning" in normalized
        else:
            ok = "nhanh" in normalized or "fast" in normalized or "quick" in normalized
        return ok, current

    try:
        page.wait_for_timeout(2000)

        open_result = open_model_menu()

        if not open_result.get("ok"):
            print(f"[{engine}] ⚠ Không mở được menu model")
            return False

        print(f"[{engine}] ✓ Đã mở menu model (button: '{open_result.get('text')}', score={open_result.get('score')})")
        page.wait_for_timeout(1200)

        if timestamp and output_dir:
            try:
                debug_dir = output_dir / "debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                debug_png = debug_dir / f"gemini_model_menu_open_{timestamp}.png"
                page.screenshot(path=str(debug_png), full_page=True)
                print(f"[{engine}] 🧪 Snapshot menu: {debug_png}")
            except Exception as e:
                print(f"[{engine}] ⚠ Không lưu snapshot menu được: {e}")

        menu_info = collect_menu_info()

        option_texts = [opt.get("text", "") for opt in menu_info.get("options", [])]
        if option_texts:
            print(f"[{engine}] Model options thấy được: {' | '.join(option_texts)}")
        else:
            print(f"[{engine}] ⚠ Không đọc được option nào trong menu model")

        selected_thinking = click_model_option("thinking")

        if selected_thinking.get("ok"):
            page.wait_for_timeout(900)
            verified_thinking, current_model = verify_model("thinking")
            if verified_thinking:
                print(
                    f"[{engine}] ✓ Đã chọn model Tư duy: '{selected_thinking.get('model')}' "
                    f"(chip hiện tại: '{current_model.get('text')}')"
                )

                # Chụp snapshot SAU KHI chọn Tư duy để verify
                if timestamp and output_dir:
                    try:
                        debug_dir = output_dir / "debug"
                        debug_png = debug_dir / f"gemini_after_select_thinking_{timestamp}.png"
                        page.screenshot(path=str(debug_png), full_page=True)
                        print(f"[{engine}] 🧪 Snapshot sau khi chọn Tư duy: {debug_png}")
                    except Exception as e:
                        print(f"[{engine}] ⚠ Không lưu snapshot sau chọn được: {e}")

                return True

            print(
                f"[{engine}] ⚠ Đã click Tư duy nhưng chip hiện tại vẫn là "
                f"'{current_model.get('text') or 'không đọc được'}'"
            )

        else:
            print(f"[{engine}] ⚠ Không thấy option Tư duy khả dụng")

        print(f"[{engine}] ⚠ Fallback sang Nhanh...")

        if not ensure_model_menu_open():
            print(f"[{engine}] ⚠ Không mở lại được menu model để fallback")
            return False

        selected_fast = click_model_option("fast")

        if selected_fast.get("ok"):
            page.wait_for_timeout(900)
            verified_fast, current_model = verify_model("fast")
            if verified_fast:
                print(
                    f"[{engine}] ✓ Đã fallback sang Nhanh: '{selected_fast.get('model')}' "
                    f"(chip hiện tại: '{current_model.get('text')}')"
                )
                return True

            print(
                f"[{engine}] ⚠ Đã click Nhanh nhưng chip hiện tại vẫn là "
                f"'{current_model.get('text') or 'không đọc được'}'"
            )

        print(f"[{engine}] ⚠ Không chọn được Tư duy hoặc Nhanh, giữ model hiện tại")
        page.keyboard.press("Escape")
        return False

    except Exception as e:
        print(f"[{engine}] ⚠ Lỗi khi chọn model: {e}")
        return False



def main():
    try:
        args = parse_worker_args(sys.argv, "search_gemini.py")
    except ValueError as e:
        print(str(e))
        sys.exit(1)

    engine = "Gemini"
    timestamp = args["timestamp"]

    if args["mode"] == "setup":
        open_real_browser_for_setup(engine, PROFILE_DIR, "https://gemini.google.com/app")
        return

    query = args["query"]
    log_enabled = args["log_enabled"]
    result = {"success": False, "data": None, "error": None, "time": 0}
    start_time = datetime.now()

    ensure_dirs(PROFILE_DIR, OUTPUT_DIR, TEMP_DIR)

    browser = None
    context = None
    page = None
    chrome_process = None
    stdout_cm = build_stdout_context(log_enabled)

    with stdout_cm:
        if log_enabled:
            print(f"\n[{engine}] Bắt đầu...")

        try:
            with sync_playwright() as p:
                browser, context, page, chrome_process = launch_real_chrome_with_cdp(
                    playwright=p,
                    engine=engine,
                    profile_dir=PROFILE_DIR,
                    start_url="https://gemini.google.com/app",
                    cdp_port=CDP_PORT,
                    timeout=30000,
                )

                page.set_default_timeout(TIMEOUT_MS)
                page.bring_to_front()

                print(f"[{engine}] Đang mở Gemini...")
                page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                blockers = detect_page_blockers(
                    page,
                    login_keywords=["sign in", "log in", "login", "đăng nhập", "dang nhap"],
                    captcha_keywords=["captcha", "verify", "robot"],
                    logout_keywords=["signed out"],
                )
                if blockers.get("hasCaptcha"):
                    raise Exception("Gemini yêu cầu CAPTCHA - cần xác minh thủ công trong profile")
                if blockers.get("hasLoginPrompt") or blockers.get("hasLogoutMarker"):
                    raise Exception("Gemini chưa đăng nhập trong profile - hãy chạy --setup")

                # Chọn model: ưu tiên Tư duy/Thinking, fallback sang Nhanh/Fast nếu verify thất bại
                print(f"[{engine}] Đang chọn model...")
                select_model_with_fallback(page, engine, timestamp, OUTPUT_DIR)

                print(f"[{engine}] Đang nhập câu hỏi...")
                textarea = page.wait_for_selector('div[contenteditable="true"][role="textbox"]', timeout=10000)
                textarea.click()
                page.wait_for_timeout(300)
                textarea.fill(query)
                page.wait_for_timeout(500)
                textarea.press("Enter")

                page.wait_for_timeout(2000)

                def is_gemini_busy():
                    return page.evaluate("""
                        () => {
                            const buttons = document.querySelectorAll('button');
                            for (const btn of buttons) {
                                const aria = btn.getAttribute('aria-label') || '';
                                if (aria.includes('Dừng') || aria.includes('Stop')) {
                                    return true;
                                }
                            }
                            const bodyText = document.body.innerText;
                            if (bodyText.includes('Đang tạo') || bodyText.includes('Generating')) {
                                return true;
                            }
                            return false;
                        }
                    """)

                prev_text = ""
                stable_count = 0
                max_wait = 180
                has_content = False
                min_success_chars = 20

                print(f"[{engine}] Đang đợi response...")

                for i in range(max_wait):
                    page.wait_for_timeout(1000)
                    is_busy = is_gemini_busy()

                    current_response = page.evaluate("""
                        () => {
                            const bodyText = document.body.innerText;
                            const markers = [
                                "Gemini đã nói",
                                "Gemini said",
                                "Gemini",
                            ];

                            let startIdx = -1;
                            let startMarker = "";

                            for (const marker of markers) {
                                startIdx = bodyText.indexOf(marker);
                                if (startIdx !== -1) {
                                    startMarker = marker;
                                    break;
                                }
                            }

                            if (startIdx === -1) return '';

                            startIdx += startMarker.length;

                            const endMarkers = ["\\nCông cụ\\n", "\\nGemini là AI", "\\nCâu trả lời tốt"];
                            let endIdx = bodyText.length;

                            for (const marker of endMarkers) {
                                const idx = bodyText.indexOf(marker, startIdx);
                                if (idx !== -1 && idx < endIdx) {
                                    endIdx = idx;
                                }
                            }

                            return bodyText.substring(startIdx, endIdx).trim();
                        }
                    """)

                    if is_busy:
                        if i % 10 == 0:
                            print(f"[{engine}] Đang suy nghĩ... ({i}s)")
                        stable_count = 0
                        prev_text = current_response
                        continue

                    if current_response and len(current_response) >= min_success_chars:
                        has_content = True

                        if current_response == prev_text:
                            stable_count += 1
                            if stable_count >= 5:
                                print(f"[{engine}] ✓ Text ổn định sau {i}s ({len(current_response)} chars)")
                                break
                        else:
                            if i % 5 == 0:
                                print(f"[{engine}] Đang nhận response... ({len(current_response)} chars)")
                            stable_count = 0
                            prev_text = current_response
                    else:
                        if i % 10 == 0 and not has_content:
                            print(f"[{engine}] Chưa có response... ({i}s)")
                        stable_count = 0
                        prev_text = current_response

                response_text = prev_text if prev_text else ""

                if has_content and len(response_text.strip()) >= min_success_chars:
                    result["success"] = True
                    result["data"] = response_text.strip()
                    print(f"[{engine}] ✓ Thành công ({len(response_text)} chars)")
                else:
                    result["error"] = "Response quá ngắn hoặc không lấy được"
                    print(f"[{engine}] ✗ Lỗi: {result['error']}")
                    if response_text:
                        result["data"] = response_text

                save_storage_state(context, STORAGE_STATE_PATH, engine)

        except PlaywrightTimeoutError as e:
            result["error"] = f"Timeout: {str(e)}"
            print(f"[{engine}] ✗ Timeout: {e}")
        except Exception as e:
            result["error"] = f"Lỗi: {str(e)}"
            print(f"[{engine}] ✗ Lỗi: {e}")
        finally:
            try:
                if page:
                    page.wait_for_timeout(2000)
            except Exception:
                pass
            close_attached_browser(browser, chrome_process)

    result["time"] = (datetime.now() - start_time).total_seconds()

    finalize_worker_run(engine, TEMP_DIR, "gemini", timestamp, result, log_enabled)
    sys.exit(0 if result["success"] else 1)

if __name__ == "__main__":
    main()
