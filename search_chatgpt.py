"""
Search ChatGPT - Standalone Script
Profile: profiles/chatgpt/
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
PROFILE_DIR = BASE_DIR / "profiles" / "chatgpt"
STORAGE_STATE_PATH = BASE_DIR / "profiles" / "chatgpt_storage_state.json"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = OUTPUT_DIR / "temp"
DEBUG_DIR = OUTPUT_DIR / "debug"
TIMEOUT_MS = 60000
CDP_PORT = 9331

def _verify_web_search_on(page) -> bool:
    """Verify web search đã ON bằng cách tìm 'Search' hoặc '🌐' ở composer area."""
    try:
        result = page.evaluate(r"""
            () => {
                const norm = (t) => (t || '').replace(/\s+/g,' ').trim().toLowerCase();
                
                // Tìm "Search" hoặc "🌐" ở nửa dưới màn hình
                let foundSearch = false;
                let foundGlobe = false;
                const debugInfo = { searchTexts: [], globeTexts: [] };
                
                const allEls = Array.from(document.querySelectorAll('*'));
                for (const el of allEls) {
                    const r = el.getBoundingClientRect();
                    // Bỏ filter size để tìm tất cả
                    if (r.top < window.innerHeight * 0.5) continue;  // Chỉ nửa dưới
                    
                    const s = getComputedStyle(el);
                    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') continue;
                    
                    const text = norm(el.innerText || el.textContent || '');
                    
                    // Tìm "search"
                    if (text.includes('search')) {
                        foundSearch = true;
                        debugInfo.searchTexts.push(text.slice(0, 50));
                    }
                    
                    // Tìm globe emoji
                    const rawText = el.innerText || el.textContent || '';
                    if (rawText.includes('🌐')) {
                        foundGlobe = true;
                        debugInfo.globeTexts.push(rawText.slice(0, 50));
                    }
                }
                
                return {
                    success: foundSearch && foundGlobe,
                    foundSearch,
                    foundGlobe,
                    debugInfo
                };
            }
        """)
        
        print(f"[Verify Debug] foundSearch={result.get('foundSearch')}, foundGlobe={result.get('foundGlobe')}")
        print(f"[Verify Debug] searchTexts={result.get('debugInfo', {}).get('searchTexts', [])[:3]}")
        print(f"[Verify Debug] globeTexts={result.get('debugInfo', {}).get('globeTexts', [])[:3]}")
        
        return result.get('success', False)
    except Exception as e:
        print(f"[Verify Debug] Exception: {e}")
        return False


def enable_web_search(page, engine, timestamp):
    """Bật Web search bằng cách click vào menu.

    Cơ chế (2026-04-02 v7 - check trước nếu đã ON):
    Menu "+" = các <div class="group __menu-item">:
      [💭] Đang suy nghĩ
      [🔬] Nghiên cứu chuyên sâu
      [⋯] Thêm  ← SUBMENU chứa "Search the web"
    Phải HOVER (không phải click) vào "Thêm" để mở submenu, rồi click "Search the web" / "Tìm kiếm trên mạng".
    Nếu không tìm thấy "Tìm kiếm trên mạng" trong submenu → đã BẬT rồi.
    """
    try:
        print(f"[{engine}] Đang bật Tìm kiếm trên mạng...")

        def open_plus_menu():
            plus_btn = page.locator("[data-testid=composer-plus-btn]").first
            plus_btn.click(timeout=15000, force=True)
            page.wait_for_timeout(1500)  # Menu animation

        def hover_them_to_open_submenu():
            """
            HOVER vào "Thêm" để mở submenu - đã verify bằng debug script v8.
            Trả về tọa độ để Playwright hover.
            """
            them_info = page.evaluate(r"""() => {
                const results = { found: false, them_text: '', x: 0, y: 0, all_items: [] };

                // Tìm menu items
                const menuItems = Array.from(document.querySelectorAll('div.__menu-item, div[role="menuitem"]'));
                console.log('[WS] Found', menuItems.length, 'menu items');

                for (const el of menuItems) {
                    const r = el.getBoundingClientRect();
                    if (r.width < 10 || r.height < 8) continue;
                    const s = getComputedStyle(el);
                    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') continue;

                    let directText = '';
                    for (const c of el.childNodes) {
                        if (c.nodeType === 3) directText += (c.textContent || '').trim();
                    }
                    const text = directText || (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60);
                    results.all_items.push({ text, x: Math.round(r.x), y: Math.round(r.y) });
                    console.log('[WS] Item:', text, '@', Math.round(r.x), Math.round(r.y));

                    // Tìm "Thêm" — có aria-haspopup="menu"
                    if ((text === 'Thêm' || text === 'More') && 
                        (el.getAttribute('aria-haspopup') === 'menu' || text === 'Thêm')) {
                        results.found = true;
                        results.them_text = text;
                        // Tọa độ trung tâm để hover
                        results.x = Math.round(r.x + r.width / 2);
                        results.y = Math.round(r.y + r.height / 2);
                        return results;
                    }
                }
                return results;
            }""")
            
            if them_info.get('found'):
                # Dùng Playwright mouse.move để hover
                page.mouse.move(them_info['x'], them_info['y'])
                print(f"[{engine}]   - Hovered 'Thêm' at ({them_info['x']}, {them_info['y']})")
            
            return them_info
        
        def click_web_search_in_submenu():
            """Sau khi hover 'Thêm', click 'Search the web' trong submenu mở ra."""
            return page.evaluate(r"""() => {
                const patterns = [/^search\s*the\s*web$/i, /^web\s*search$/i, /tìm kiếm trên web/i, /tìm kiếm trên mạng/i];
                const skip = [/tệp/i, /tải lên/i, /download/i, /upload/i];

                const nodes = Array.from(document.querySelectorAll('.__menu-item, [role="menuitem"], [role="option"]'));
                let best = null, bestP = 999;
                for (const el of nodes) {
                    const r = el.getBoundingClientRect();
                    if (r.width < 20 || r.height < 8) continue;
                    const s = getComputedStyle(el);
                    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') continue;
                    let dt = '';
                    for (const c of el.childNodes) { if (c.nodeType === 3) dt += (c.textContent||'').trim(); }
                    const text = (dt || el.innerText || '').replace(/\s+/g, ' ').trim();
                    if (!text || text.length > 80) continue;
                    if (skip.some(p => p.test(text))) continue;
                    for (let i = 0; i < patterns.length; i++) {
                        if (patterns[i].test(text)) {
                            if (i < bestP) { bestP = i; best = el; }
                            console.log('[WS_sub] candidate:', text, 'prio', i);
                        }
                    }
                }
                if (best) { best.click(); return { clicked: true, text: (best.innerText || '').slice(0,40) }; }
                return { clicked: false };
            }""")

        # === CHỈ CLICK 1 LẦN, KHÔNG VERIFY ===
        print(f"[{engine}]   - Click + → Hover Thêm → Check submenu")
        open_plus_menu()

        result1 = hover_them_to_open_submenu()
        print(f"[{engine}]   - Hover 'Thêm': {result1.get('found')} ('{result1.get('them_text', '')}')")

        if not result1.get('found'):
            print(f"[{engine}] ✗ Không tìm thấy 'Thêm'")
            page.keyboard.press("Escape")
            return False

        # Chờ submenu mở sau khi hover
        page.wait_for_timeout(2000)
        try:
            dbg_hover = DEBUG_DIR / f"chatgpt_submenu_after_hover_them_{timestamp}.png"
            page.screenshot(path=str(dbg_hover), full_page=True)
            print(f"[{engine}] 🧪 Submenu screenshot: {dbg_hover}")
        except Exception:
            pass

        result2 = click_web_search_in_submenu()
        print(f"[{engine}]   - Click WS: {result2}")

        if not result2.get('clicked'):
            print(f"[{engine}] ℹ Không tìm thấy 'Tìm kiếm trên mạng' - có thể đã BẬT rồi")
            page.keyboard.press("Escape")
            return True  # Coi như đã ON

        page.wait_for_timeout(2000)
        print(f"[{engine}] ✓ Đã click '{result2.get('text', '')}' - Web Search ON")
        
        try:
            dbg = DEBUG_DIR / f"chatgpt_websearch_enabled_{timestamp}.png"
            page.screenshot(path=str(dbg), full_page=True)
            print(f"[{engine}] 🧪 Screenshot: {dbg}")
        except Exception:
            pass

        return True

    except Exception as e:
        print(f"[{engine}] ⚠ Lỗi enable_web_search: {e}")
        return False


def ensure_logged_in_chat_ui(page, engine):
    try:
        page.wait_for_selector("#prompt-textarea", timeout=12000)
        return
    except Exception:
        pass

    current_url = page.url
    page_text = ""
    try:
        page_text = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        pass

    if "log in" in page_text or "đăng nhập" in page_text or "sign up" in page_text or "bắt đầu" in page_text:
        raise Exception("ChatGPT chưa đăng nhập trong profile - hãy chạy --setup")

    raise Exception(
        f"ChatGPT chưa vào được giao diện chat đã đăng nhập (url hiện tại: {current_url}) - hãy chạy --setup"
    )


def refresh_storage_state_from_profile(engine):
    if not PROFILE_DIR.exists():
        return False

    print(f"[{engine}] Đang thử đồng bộ storage_state từ profile Chrome thật...")
    context = None
    page = None
    try:
        with sync_playwright() as p:
            context = launch_persistent_context(
                playwright=p,
                profile_dir=PROFILE_DIR,
                engine=engine,
                storage_state_path=None,
                timeout=30000,
                extra_args=MANUAL_SETUP_BROWSER_ARGS,
                load_saved_state=False,
                apply_stealth=False,
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(TIMEOUT_MS)
            page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            save_storage_state(context, STORAGE_STATE_PATH, engine)
            return True
    except Exception as exc:
        print(f"[{engine}] ⚠ Không đồng bộ được storage_state từ profile: {exc}")
        return False
    finally:
        if context:
            try:
                if page:
                    page.wait_for_timeout(500)
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass


def main():
    try:
        args = parse_worker_args(sys.argv, "search_chatgpt.py")
    except ValueError as e:
        print(str(e))
        sys.exit(1)

    engine = "ChatGPT"
    timestamp = args["timestamp"]

    if args["mode"] == "setup":
        open_real_browser_for_setup(engine, PROFILE_DIR, "https://chatgpt.com/")
        return

    query = args["query"]
    log_enabled = args["log_enabled"]

    result = {"success": False, "data": None, "error": None, "time": 0}
    start_time = datetime.now()

    ensure_dirs(PROFILE_DIR, OUTPUT_DIR, TEMP_DIR, DEBUG_DIR)

    browser = None
    context = None
    page = None
    chrome_process = None
    stdout_cm = build_stdout_context(log_enabled)

    with stdout_cm:
        if log_enabled:
            print(f"\n[{engine}] Bắt đầu...")
            print(f"[{engine}] Timestamp: {timestamp}")

        try:
            with sync_playwright() as p:
                browser, context, page, chrome_process = launch_real_chrome_with_cdp(
                    playwright=p,
                    engine=engine,
                    profile_dir=PROFILE_DIR,
                    start_url="https://chatgpt.com/",
                    cdp_port=CDP_PORT,
                    timeout=30000,
                )

                page.set_default_timeout(TIMEOUT_MS)
                page.bring_to_front()

                print(f"[{engine}] Đang mở ChatGPT...")
                page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                ensure_logged_in_chat_ui(page, engine)

                blockers = detect_page_blockers(
                    page,
                    login_keywords=["log in", "login", "sign up", "đăng nhập", "đăng ký"],
                    captcha_keywords=["verify you are human", "captcha", "robot"],
                    logout_keywords=["signed out"],
                )
                if blockers.get("hasCaptcha"):
                    raise Exception("ChatGPT yêu cầu CAPTCHA - cần xác minh thủ công trong profile")
                if blockers.get("hasLoginPrompt") or blockers.get("hasLogoutMarker"):
                    raise Exception("ChatGPT chưa đăng nhập trong profile - hãy chạy --setup")

                page.wait_for_timeout(2000)
                enabled = enable_web_search(page, engine, timestamp)

                try:
                    dbg_png = DEBUG_DIR / f"chatgpt_tools_{timestamp}.png"
                    dbg_html = DEBUG_DIR / f"chatgpt_tools_{timestamp}.html"
                    page.screenshot(path=str(dbg_png), full_page=True)
                    dbg_html.write_text(page.content(), encoding="utf-8")
                    print(f"[{engine}] 🧪 Debug saved: {dbg_png}")
                    print(f"[{engine}] 🧪 Debug saved: {dbg_html}")
                except Exception as e:
                    print(f"[{engine}] ⚠ Không lưu debug được: {e}")

                if not enabled:
                    result["error"] = "BẮT BUỘC Web Search ON nhưng không bật được (UI/feature bị ẩn hoặc selector không khớp)"
                    print(f"[{engine}] ✗ {result['error']}")
                    try:
                        dbg_fail_png = DEBUG_DIR / f"chatgpt_websearch_fail_{timestamp}.png"
                        dbg_fail_html = DEBUG_DIR / f"chatgpt_websearch_fail_{timestamp}.html"
                        page.screenshot(path=str(dbg_fail_png), full_page=True)
                        dbg_fail_html.write_text(page.content(), encoding="utf-8")
                        print(f"[{engine}] 🧪 Debug saved: {dbg_fail_png}")
                        print(f"[{engine}] 🧪 Debug saved: {dbg_fail_html}")
                    except Exception as e:
                        print(f"[{engine}] ⚠ Không lưu debug fail-websearch được: {e}")

                    save_storage_state(context, STORAGE_STATE_PATH, engine)
                    raise Exception(result["error"])

                print(f"[{engine}] Đang nhập câu hỏi...")
                textarea = page.wait_for_selector("#prompt-textarea", timeout=10000)
                textarea.click()
                textarea.fill(query)

                send_button = page.wait_for_selector('button[data-testid="send-button"]', timeout=5000)
                send_button.click()

                page.wait_for_timeout(2000)

                try:
                    dbg2_png = DEBUG_DIR / f"chatgpt_after_send_{timestamp}.png"
                    dbg2_html = DEBUG_DIR / f"chatgpt_after_send_{timestamp}.html"
                    page.screenshot(path=str(dbg2_png), full_page=True)
                    dbg2_html.write_text(page.content(), encoding="utf-8")
                    print(f"[{engine}] 🧪 Debug saved: {dbg2_png}")
                    print(f"[{engine}] 🧪 Debug saved: {dbg2_html}")
                except Exception as e:
                    print(f"[{engine}] ⚠ Không lưu debug after_send được: {e}")

                def is_chatgpt_busy():
                    return page.evaluate(r"""
                        () => {
                            const buttons = Array.from(document.querySelectorAll('button'));
                            for (const btn of buttons) {
                                const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                                if (aria.includes('stop') || aria.includes('dừng')) return true;
                            }
                            const ta = document.querySelector('#prompt-textarea');
                            if (ta && ta.hasAttribute('disabled')) return true;
                            return false;
                        }
                    """)

                def looks_like_ui_noise(t: str) -> bool:
                    if not t or not t.strip():
                        return True
                    low = t.strip().lower()
                    bad = [
                        'log in', 'login', 'sign up', 'đăng nhập', 'đăng ký',
                        'something went wrong', 'có lỗi', 'try again', 'thử lại',
                        'verify you are human', 'captcha'
                    ]
                    return any(x in low for x in bad)

                prev_text = ""
                stable_count = 0
                max_wait = 180
                stable_needed = 3

                def scrape_last_assistant_text():
                    return page.evaluate(r"""
                        () => {
                            const norm = (t) => (t || '').replace(/\s+$/g,'').trim();
                            const assistantNodes = document.querySelectorAll('[data-message-author-role="assistant"]');
                            if (assistantNodes && assistantNodes.length) {
                                const last = assistantNodes[assistantNodes.length - 1];
                                const content = last.querySelector('.markdown, .prose') || last;
                                let t = norm(content.innerText);
                                const lines = t.split('\n').map(x => x.trim());
                                const filtered = [];
                                for (const line of lines) {
                                    if (/^[a-z0-9.-]+\.[a-z]{2,}(\/.*)?$/i.test(line) && line.length <= 60) {
                                        continue;
                                    }
                                    filtered.push(line);
                                }
                                t = filtered.join('\n').trim();
                                return t;
                            }

                            const articles = document.querySelectorAll('article[data-testid^="conversation-turn"]');
                            if (articles && articles.length) {
                                const lastArticle = articles[articles.length - 1];
                                const content = lastArticle.querySelector('.markdown, .prose') || lastArticle;
                                let text = norm(content.innerText);
                                text = text.replace(/^ChatGPT( đã nói:| said:)?\s*/i, '').trim();
                                return text;
                            }

                            const main = document.querySelector('main');
                            return main ? norm(main.innerText) : '';
                        }
                    """)

                for i in range(max_wait):
                    page.wait_for_timeout(1000)

                    try:
                        is_busy = is_chatgpt_busy()
                    except Exception:
                        is_busy = True

                    try:
                        current_response = scrape_last_assistant_text()
                    except Exception:
                        current_response = ""

                    if is_busy:
                        if i % 10 == 0:
                            print(f"[{engine}] Đang tạo response... ({i}s)")
                        stable_count = 0
                        if current_response:
                            prev_text = current_response
                        continue

                    if current_response and (not looks_like_ui_noise(current_response)):
                        if current_response == prev_text:
                            stable_count += 1
                            if stable_count >= stable_needed:
                                print(f"[{engine}] ✓ Text ổn định sau {i}s")
                                break
                        else:
                            if i % 5 == 0:
                                print(f"[{engine}] Đang nhận response... ({len(current_response)} chars)")
                            stable_count = 0
                            prev_text = current_response
                    else:
                        stable_count = 0
                        if current_response:
                            prev_text = current_response

                response_text = (prev_text or "").strip()

                if response_text and (not looks_like_ui_noise(response_text)):
                    result["success"] = True
                    result["data"] = response_text
                    print(f"[{engine}] ✓ Thành công ({len(response_text)} chars)")
                else:
                    result["error"] = "Response rỗng/không hợp lệ hoặc không scrape được"
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
    finalize_worker_run(engine, TEMP_DIR, "chatgpt", timestamp, result, log_enabled)
    sys.exit(0 if result["success"] else 1)

if __name__ == "__main__":
    main()








