from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from random import Random
from threading import Event, RLock, Thread
from time import monotonic
from typing import Callable
from urllib.parse import urlparse
import webbrowser

if sys.platform != "darwin":
    raise SystemExit("This script currently supports macOS only.")

try:
    import ApplicationServices as AS
except ImportError:
    raise SystemExit(
        "Install macOS accessibility support first: "
        "pip install pyobjc-framework-ApplicationServices"
    ) from None

try:
    import pyautogui
except ImportError:
    raise SystemExit("Install PyAutoGUI first: pip install pyautogui") from None

try:
    from pynput import keyboard
except ImportError:
    raise SystemExit("Install pynput first: pip install pynput") from None


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IntensityProfile:
    scroll_min: int
    scroll_max: int
    move_duration_min: float
    move_duration_max: float
    tab_max: int
    switch_probability: float
    pause_min: float
    pause_max: float


@dataclass(frozen=True, slots=True)
class ActivityConfig:
    # Set intensity to: very_low, low, medium, high, or very_high.
    intensity: str = "medium"

    enable_mouse_movement: bool = True
    enable_scrolling: bool = True
    enable_keyboard_tabbing: bool = False
    enable_window_switching: bool = True
    enable_text_cursor_clicking: bool = True

    # Chance of executing an action during each cycle.
    action_execution_probability: float = 1.0

    # Keep random movement away from PyAutoGUI's corner fail-safe points.
    safe_screen_margin: int = 10
    command_tab_max_steps: int = 5
    dry_run: bool = False


# Edit these defaults to change normal script behavior.
CONFIG = ActivityConfig()


INTENSITY_SETTINGS = {
    "very_low": IntensityProfile(2, 8, 0.1, 0.4, 1, 0.02, 2.0, 5.0),
    "low": IntensityProfile(5, 15, 0.2, 0.6, 2, 0.05, 1.0, 3.0),
    "medium": IntensityProfile(15, 30, 0.5, 1.5, 3, 0.10, 0.5, 2.0),
    "high": IntensityProfile(40, 80, 1.0, 2.5, 5, 0.15, 0.2, 1.0),
    "very_high": IntensityProfile(80, 150, 1.5, 3.0, 5, 0.20, 0.1, 0.5),
}


EDITABLE_TEXT_ROLES = {
    "AXTextField",
    "AXTextArea",
    "AXTextView",
    "AXSearchField",
    "AXComboBox",
}


def validate_config(
    config: ActivityConfig,
    *,
    require_enabled: bool = True,
) -> IntensityProfile:
    if config.intensity not in INTENSITY_SETTINGS:
        choices = ", ".join(INTENSITY_SETTINGS)
        raise ValueError(f"intensity must be one of: {choices}")

    if not 0.0 <= config.action_execution_probability <= 1.0:
        raise ValueError("action_execution_probability must be between 0 and 1")
    if config.safe_screen_margin < 0:
        raise ValueError("safe_screen_margin cannot be negative")
    if config.command_tab_max_steps < 1:
        raise ValueError("command_tab_max_steps must be at least 1")

    enabled = (
        config.enable_mouse_movement,
        config.enable_scrolling,
        config.enable_keyboard_tabbing,
        config.enable_window_switching,
        config.enable_text_cursor_clicking,
    )
    if require_enabled and not any(enabled):
        raise ValueError("Enable at least one activity feature")

    profile = INTENSITY_SETTINGS[config.intensity]
    if profile.scroll_min < 1 or profile.scroll_max < profile.scroll_min:
        raise ValueError("Invalid scroll range in the selected intensity profile")
    if profile.move_duration_min < 0 or profile.move_duration_max < profile.move_duration_min:
        raise ValueError("Invalid movement duration range in the selected profile")
    if profile.tab_max < 1:
        raise ValueError("tab_max must be at least 1")
    if not 0.0 <= profile.switch_probability <= 1.0:
        raise ValueError("switch_probability must be between 0 and 1")
    if profile.pause_min < 0 or profile.pause_max < profile.pause_min:
        raise ValueError("Invalid pause range in the selected intensity profile")
    return profile


class RuntimeSettings:
    """Thread-safe settings shared by the GUI and the automation worker."""

    def __init__(self, config: ActivityConfig) -> None:
        validate_config(config, require_enabled=False)
        self._config = config
        self._lock = RLock()

    def snapshot(self) -> tuple[ActivityConfig, IntensityProfile]:
        with self._lock:
            config = self._config
            return config, validate_config(config, require_enabled=False)

    def update(self, **changes: object) -> ActivityConfig:
        with self._lock:
            updated = replace(self._config, **changes)
            validate_config(updated, require_enabled=False)
            self._config = updated
            return updated


class HotkeyController:
    """Track hotkey state without confusing the left and right Control keys."""

    control_keys = {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
    toggle_key = keyboard.KeyCode.from_char("1")
    stop_key = keyboard.KeyCode.from_char("2")

    def __init__(
        self,
        running_event: Event,
        stop_event: Event,
        state_changed: Callable[[], None] | None = None,
    ) -> None:
        self.running_event = running_event
        self.stop_event = stop_event
        self.state_changed = state_changed
        self.controls_down: set[object] = set()
        self.toggle_key_down = False
        self.stop_key_down = False

    def on_press(self, key: object) -> bool | None:
        if key in self.control_keys:
            self.controls_down.add(key)
            return None

        if key == self.toggle_key and self.controls_down and not self.toggle_key_down:
            self.toggle_key_down = True
            if self.running_event.is_set():
                self.running_event.clear()
                print("Paused by Ctrl+1", flush=True)
            else:
                self.running_event.set()
                print("Resumed by Ctrl+1", flush=True)
            self._notify_state_changed()

        if key == self.stop_key and self.controls_down and not self.stop_key_down:
            self.stop_key_down = True
            self.stop_event.set()
            self.running_event.set()  # Wake the main loop if it is paused.
            print("Stopping by Ctrl+2", flush=True)
            self._notify_state_changed()
            return False

        return None

    def _notify_state_changed(self) -> None:
        if self.state_changed is not None:
            self.state_changed()

    def on_release(self, key: object) -> None:
        if key in self.control_keys:
            self.controls_down.discard(key)
        elif key == self.toggle_key:
            self.toggle_key_down = False
        elif key == self.stop_key:
            self.stop_key_down = False


class ActivitySimulator:
    def __init__(
        self,
        settings: RuntimeSettings,
        running_event: Event,
        stop_event: Event,
        rng: Random | None = None,
    ) -> None:
        self.settings = settings
        self.running_event = running_event
        self.stop_event = stop_event
        self.rng = rng or Random()
        self._accessibility_warning_shown = False
        self._screen_size_warning_shown = False

    def input_allowed(self) -> bool:
        return self.running_event.is_set() and not self.stop_event.is_set()

    def enabled_actions(self, config: ActivityConfig) -> tuple[str, ...]:
        actions: list[str] = []
        if config.enable_mouse_movement:
            actions.append("move")
        if config.enable_scrolling:
            actions.append("scroll")
        if config.enable_keyboard_tabbing:
            actions.append("tabs")
        if config.enable_text_cursor_clicking:
            actions.append("text_cursor_click")
        return tuple(actions)

    def sleep_with_control(self, seconds: float, check_interval: float = 0.1) -> bool:
        """Sleep until the duration ends, or return early on pause/stop."""
        end_time = monotonic() + max(0.0, seconds)

        while monotonic() < end_time:
            if not self.input_allowed():
                return False
            remaining = end_time - monotonic()
            if self.stop_event.wait(min(check_interval, max(0.0, remaining))):
                return False

        return self.input_allowed()

    def random_delay(self, minimum: float, maximum: float) -> bool:
        return self.sleep_with_control(self.rng.uniform(minimum, maximum))

    def safe_random_coordinate(self, limit: int, margin: int | None = None) -> int:
        if limit <= 1:
            return 0

        if margin is None:
            margin = self.settings.snapshot()[0].safe_screen_margin
        margin = min(margin, (limit - 1) // 2)
        return self.rng.randint(margin, limit - margin - 1)

    def random_move(self) -> None:
        if not self.input_allowed():
            return

        config, profile = self.settings.snapshot()
        width, height = pyautogui.size()
        minimum_dimension = (config.safe_screen_margin * 2) + 1
        if width < minimum_dimension or height < minimum_dimension:
            if not self._screen_size_warning_shown:
                LOGGER.warning(
                    "Skipping mouse movement because PyAutoGUI reported an invalid "
                    "screen size: %sx%s",
                    width,
                    height,
                )
                self._screen_size_warning_shown = True
            return

        x = self.safe_random_coordinate(width, config.safe_screen_margin)
        y = self.safe_random_coordinate(height, config.safe_screen_margin)
        duration = self.rng.uniform(
            profile.move_duration_min,
            profile.move_duration_max,
        )

        if not self.input_allowed():
            return
        if config.dry_run:
            LOGGER.info("DRY RUN: move mouse to (%s, %s) over %.2fs", x, y, duration)
            return
        pyautogui.moveTo(x, y, duration=duration)

    def random_scroll(self) -> None:
        if not self.input_allowed():
            return

        config, profile = self.settings.snapshot()
        amount = self.rng.randint(profile.scroll_min, profile.scroll_max)
        amount *= self.rng.choice((-1, 1))
        if not self.input_allowed():
            return
        if config.dry_run:
            LOGGER.info("DRY RUN: scroll %s", amount)
            return
        pyautogui.scroll(amount)

    def random_tab_sequence(self) -> None:
        config, profile = self.settings.snapshot()
        tab_count = self.rng.randint(1, profile.tab_max)
        if config.dry_run:
            LOGGER.info("DRY RUN: press Tab %s time(s)", tab_count)
            return

        for _ in range(tab_count):
            if not self.input_allowed():
                return
            pyautogui.press("tab")
            if not self.random_delay(0.05, 0.2):
                return

    def _warn_about_accessibility(self, message: str) -> None:
        if not self._accessibility_warning_shown:
            LOGGER.warning("Accessibility lookup failed: %s", message)
            self._accessibility_warning_shown = True

    def is_editable_text_under_mouse(self) -> bool:
        x, y = pyautogui.position()

        try:
            system_wide = AS.AXUIElementCreateSystemWide()
            error, element = AS.AXUIElementCopyElementAtPosition(system_wide, x, y, None)
            if error != 0 or not element:
                if error == getattr(AS, "kAXErrorAPIDisabled", -1):
                    self._warn_about_accessibility(
                        "grant Accessibility permission in System Settings > Privacy & Security"
                    )
                return False

            error, role = AS.AXUIElementCopyAttributeValue(
                element,
                AS.kAXRoleAttribute,
                None,
            )
            if error != 0 or str(role) not in EDITABLE_TEXT_ROLES:
                return False

            # Secure text fields must never be clicked automatically.
            error, subrole = AS.AXUIElementCopyAttributeValue(
                element,
                AS.kAXSubroleAttribute,
                None,
            )
            if error == 0 and "secure" in str(subrole).lower():
                return False

            error, value_is_settable = AS.AXUIElementIsAttributeSettable(
                element,
                AS.kAXValueAttribute,
                None,
            )
            return error == 0 and bool(value_is_settable)
        except Exception as exc:
            self._warn_about_accessibility(str(exc))
            return False

    def click_when_text_cursor_context(self) -> None:
        if not self.input_allowed() or not self.is_editable_text_under_mouse():
            return

        if not self.input_allowed():
            return
        config, _ = self.settings.snapshot()
        if config.dry_run:
            LOGGER.info("DRY RUN: click editable text element")
            return
        pyautogui.click()

    @staticmethod
    def _release_key_without_fail_safe(key: str) -> None:
        """Release a held key even when the pointer is at a fail-safe corner."""
        fail_safe_was_enabled = pyautogui.FAILSAFE
        try:
            pyautogui.FAILSAFE = False
            pyautogui.keyUp(key)
        finally:
            pyautogui.FAILSAFE = fail_safe_was_enabled

    def switch_window(self) -> None:
        config, _ = self.settings.snapshot()
        steps = self.rng.randint(1, config.command_tab_max_steps)
        if config.dry_run:
            LOGGER.info("DRY RUN: Command+Tab %s time(s)", steps)
            return
        if not self.input_allowed():
            return

        command_is_down = False
        try:
            pyautogui.keyDown("command")
            command_is_down = True
            for _ in range(steps):
                if not self.input_allowed():
                    return
                pyautogui.press("tab")
                if not self.random_delay(0.05, 0.2):
                    return
        finally:
            if command_is_down:
                self._release_key_without_fail_safe("command")

    def select_action(self) -> str:
        config, profile = self.settings.snapshot()
        enabled_actions = self.enabled_actions(config)
        if (
            config.enable_window_switching
            and (
                not enabled_actions
                or self.rng.random() < profile.switch_probability
            )
        ):
            return "switch"
        if not enabled_actions:
            return ""
        return self.rng.choice(enabled_actions)

    def perform_action(self, action: str) -> None:
        actions = {
            "move": self.random_move,
            "scroll": self.random_scroll,
            "tabs": self.random_tab_sequence,
            "text_cursor_click": self.click_when_text_cursor_context,
            "switch": self.switch_window,
        }
        actions[action]()

    def run(self) -> None:
        while not self.stop_event.is_set():
            if not self.running_event.is_set():
                self.stop_event.wait(0.2)
                continue

            config, profile = self.settings.snapshot()
            if self.rng.random() > config.action_execution_probability:
                self.random_delay(profile.pause_min, profile.pause_max)
                continue

            action = self.select_action()
            if not action:
                self.stop_event.wait(0.2)
                continue
            self.perform_action(action)

            if self.input_allowed():
                if action == "switch":
                    self.random_delay(1.0, 3.0)
                else:
                    _, profile = self.settings.snapshot()
                    self.random_delay(profile.pause_min, profile.pause_max)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--intensity",
        choices=tuple(INTENSITY_SETTINGS),
        default=CONFIG.intensity,
        help="override the configured activity intensity",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="log actions without controlling the mouse or keyboard",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run the original terminal-only automation loop",
    )
    return parser.parse_args(argv)


def run_headless(config: ActivityConfig) -> int:
    validate_config(config)
    running_event = Event()
    running_event.set()
    stop_event = Event()
    hotkeys = HotkeyController(running_event, stop_event)
    listener = keyboard.Listener(
        on_press=hotkeys.on_press,
        on_release=hotkeys.on_release,
    )
    simulator = ActivitySimulator(
        RuntimeSettings(config),
        running_event,
        stop_event,
    )

    LOGGER.info(
        "Started headless automation at %s intensity%s. Ctrl+1 pauses; Ctrl+2 stops.",
        config.intensity,
        " in dry-run mode" if config.dry_run else "",
    )
    listener.start()

    try:
        simulator.run()
    except KeyboardInterrupt:
        LOGGER.info("Stopped by keyboard interrupt")
    except pyautogui.FailSafeException:
        LOGGER.info("Stopped by PyAutoGUI fail-safe")
    except Exception:
        LOGGER.exception("Stopped because of an unexpected error")
        return 1
    finally:
        stop_event.set()
        running_event.set()
        listener.stop()
        listener.join(timeout=1.0)

    return 0


class WebAutomationApp:
    """Thread-safe controller exposed through a local browser control panel."""

    def __init__(self, initial_config: ActivityConfig) -> None:
        self.settings = RuntimeSettings(initial_config)
        self.running_event = Event()
        self.stop_event = Event()
        self.shutdown_event = Event()
        self.worker: Thread | None = None
        self.listener: keyboard.Listener | None = None
        self.hotkeys: HotkeyController | None = None
        self.status = "Ready"
        self._lock = RLock()

    def state(self) -> dict[str, object]:
        config, _ = self.settings.snapshot()
        with self._lock:
            active = self.worker is not None and self.worker.is_alive()
            return {
                "status": self.status,
                "active": active,
                "paused": active and not self.running_event.is_set(),
                "config": {
                    "intensity": config.intensity,
                    "mouse": config.enable_mouse_movement,
                    "scroll": config.enable_scrolling,
                    "tabs": config.enable_keyboard_tabbing,
                    "switch": config.enable_window_switching,
                    "text_click": config.enable_text_cursor_clicking,
                },
            }

    def update_settings(self, changes: dict[str, object]) -> None:
        allowed = {
            "intensity": "intensity",
            "mouse": "enable_mouse_movement",
            "scroll": "enable_scrolling",
            "tabs": "enable_keyboard_tabbing",
            "switch": "enable_window_switching",
            "text_click": "enable_text_cursor_clicking",
        }
        mapped = {
            allowed[key]: value
            for key, value in changes.items()
            if key in allowed
        }
        if not mapped:
            return
        if "intensity" in mapped and mapped["intensity"] not in INTENSITY_SETTINGS:
            raise ValueError("Choose a valid intensity level")
        for key, value in mapped.items():
            if key != "intensity" and not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false")
        self.settings.update(**mapped)

    def start(self) -> None:
        with self._lock:
            if self.worker is not None and self.worker.is_alive():
                return
            config, _ = self.settings.snapshot()
            validate_config(config)
            self.running_event = Event()
            self.running_event.set()
            self.stop_event = Event()
            self.hotkeys = HotkeyController(
                self.running_event, self.stop_event, self._hotkey_changed
            )
            self.listener = keyboard.Listener(
                on_press=self.hotkeys.on_press, on_release=self.hotkeys.on_release
            )
            simulator = ActivitySimulator(self.settings, self.running_event, self.stop_event)
            self.worker = Thread(target=self._run_worker, args=(simulator,), daemon=True)
            try:
                self.listener.start()
                self.worker.start()
            except Exception:
                self.stop_event.set()
                self._stop_listener()
                self.worker = None
                raise
            self.status = "Running"

    def pause_or_resume(self) -> None:
        with self._lock:
            if self.worker is None or not self.worker.is_alive() or self.stop_event.is_set():
                return
            if self.running_event.is_set():
                self.running_event.clear()
                self.status = "Paused"
            else:
                self.running_event.set()
                self.status = "Running"

    def stop(self) -> None:
        with self._lock:
            self.stop_event.set()
            self.running_event.set()
            self._stop_listener()
            self.status = "Stopped"

    def request_shutdown(self) -> None:
        self.stop()
        self.shutdown_event.set()

    def _hotkey_changed(self) -> None:
        with self._lock:
            if self.stop_event.is_set():
                self.status = "Stopped"
                self._stop_listener()
            elif self.worker is not None and self.worker.is_alive():
                self.status = "Running" if self.running_event.is_set() else "Paused"

    def _stop_listener(self) -> None:
        if self.listener is not None:
            try:
                self.listener.stop()
            except RuntimeError:
                pass
            self.listener = None

    def _run_worker(self, simulator: ActivitySimulator) -> None:
        try:
            simulator.run()
        except pyautogui.FailSafeException:
            LOGGER.info("Automation stopped by PyAutoGUI fail-safe")
        except Exception:
            LOGGER.exception("Automation worker stopped because of an unexpected error")
        finally:
            with self._lock:
                self.stop_event.set()
                self._stop_listener()
                self.worker = None
                self.status = "Stopped"


CONTROL_PANEL_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Activity Controller</title><style>
:root{color-scheme:light;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f7fb;color:#172033}*{box-sizing:border-box}body{margin:0;padding:32px 16px}.card{max-width:620px;margin:auto;background:#fff;border:1px solid #e3e8f2;border-radius:16px;padding:28px;box-shadow:0 12px 34px #27355b12}h1{margin:0;font-size:25px}p{color:#617089;margin:8px 0 26px}.status{display:flex;justify-content:space-between;align-items:center;background:#f6f8fc;border-radius:10px;padding:15px 17px;margin-bottom:24px}.badge{font-weight:700;padding:6px 12px;border-radius:999px;background:#dbe3ef;color:#475569}.badge.Running{background:#d9f7e4;color:#166534}.badge.Paused{background:#ffedd5;color:#9a3412}.badge.Stopped{background:#fee2e2;color:#991b1b}h2{font-size:16px;margin:24px 0 12px}.row{display:flex;justify-content:space-between;gap:16px;padding:12px 0;border-bottom:1px solid #eef1f6}.row:last-child{border:0}select{min-width:155px;padding:7px;border:1px solid #cbd5e1;border-radius:7px;background:#fff}input{width:19px;height:19px;accent-color:#2563eb}.buttons{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:28px}button{border:0;border-radius:9px;padding:11px;font:inherit;font-weight:650;background:#e9eef7;color:#243047;cursor:pointer}button.primary{background:#2563eb;color:#fff}button.stop{background:#fee2e2;color:#991b1b}button:disabled{opacity:.5;cursor:not-allowed}.footer{font-size:12px;margin-top:21px;color:#758198}.quit{margin-top:14px;background:none;color:#64748b;text-decoration:underline;font-size:13px}#error{color:#b42318;font-size:13px;margin-top:12px;min-height:18px}</style></head>
<body><main class="card"><h1>Activity Controller</h1><p>Control mouse and keyboard activity from this local page.</p><section class="status"><span>Current status</span><span id="status" class="badge">Ready</span></section><h2>Settings</h2><label class="row">Intensity <select id="intensity"><option>very_low</option><option>low</option><option>medium</option><option>high</option><option>very_high</option></select></label><label class="row">Mouse movement <input id="mouse" type="checkbox"></label><label class="row">Scrolling <input id="scroll" type="checkbox"></label><label class="row">Tab navigation <input id="tabs" type="checkbox"></label><label class="row">Window switching (Command+Tab) <input id="switch" type="checkbox"></label><label class="row">Click editable text fields <input id="text_click" type="checkbox"></label><div class="buttons"><button id="start" class="primary">Start</button><button id="pause">Pause</button><button id="stop" class="stop">Stop</button></div><div id="error"></div><button id="quit" class="quit">Stop and close controller</button><div class="footer">Hotkeys: Ctrl+1 pause/resume · Ctrl+2 stop · move to a screen corner for PyAutoGUI fail-safe.</div></main><script>
const fields=['intensity','mouse','scroll','tabs','switch','text_click'];let syncing=false;
async function api(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})});const v=await r.json();if(!r.ok)throw Error(v.error||'Request failed');return v}
function apply(s){const c=s.config;syncing=true;for(const k of fields){const e=document.getElementById(k);if(e.type==='checkbox')e.checked=c[k];else e.value=c[k]}syncing=false;const badge=document.getElementById('status');badge.textContent=s.status;badge.className='badge '+s.status;document.getElementById('pause').textContent=s.paused?'Resume':'Pause';document.getElementById('start').disabled=s.active;document.getElementById('pause').disabled=!s.active;document.getElementById('stop').disabled=!s.active}
async function refresh(){try{apply(await (await fetch('/api/state')).json())}catch(e){document.getElementById('error').textContent='Controller connection lost.'}}
for(const k of fields)document.getElementById(k).addEventListener('change',async()=>{if(syncing)return;try{apply(await api('/api/settings',{[k]:document.getElementById(k).type==='checkbox'?document.getElementById(k).checked:document.getElementById(k).value}));document.getElementById('error').textContent=''}catch(e){document.getElementById('error').textContent=e.message;refresh()}});
document.getElementById('start').onclick=async()=>{try{apply(await api('/api/start'))}catch(e){document.getElementById('error').textContent=e.message}};
document.getElementById('pause').onclick=async()=>{try{apply(await api('/api/pause'))}catch(e){document.getElementById('error').textContent=e.message}};
document.getElementById('stop').onclick=async()=>{try{apply(await api('/api/stop'))}catch(e){document.getElementById('error').textContent=e.message}};
document.getElementById('quit').onclick=async()=>{await api('/api/quit');document.body.innerHTML='<main class="card"><h1>Controller stopped</h1><p>You can close this tab.</p></main>'};refresh();setInterval(refresh,800);
</script></body></html>"""


class ControlPanelHandler(BaseHTTPRequestHandler):
    """HTTP endpoints for the loopback-only control panel."""

    server: ThreadingHTTPServer

    def _json(self, status: HTTPStatus, data: dict[str, object]) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if urlparse(self.path).path == "/api/state":
            self._json(HTTPStatus.OK, self.server.controller.state())
            return
        if urlparse(self.path).path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = CONTROL_PANEL_HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("Invalid request")
            controller = self.server.controller
            path = urlparse(self.path).path
            if path == "/api/settings":
                controller.update_settings(payload)
            elif path == "/api/start":
                controller.start()
            elif path == "/api/pause":
                controller.pause_or_resume()
            elif path == "/api/stop":
                controller.stop()
            elif path == "/api/quit":
                controller.request_shutdown()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._json(HTTPStatus.OK, controller.state())
        except (TypeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            LOGGER.exception("Control-panel request failed")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def run_web_gui(config: ActivityConfig) -> int:
    """Open a local control panel without creating a native AppKit event loop."""
    validate_config(config)
    controller = WebAutomationApp(config)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ControlPanelHandler)
    server.controller = controller  # type: ignore[attr-defined]
    server.daemon_threads = True
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    LOGGER.info("Activity Controller is available at %s", url)
    if not webbrowser.open_new_tab(url):
        LOGGER.warning("Could not open a browser automatically; open %s manually", url)

    try:
        while not controller.shutdown_event.wait(0.25):
            pass
    except KeyboardInterrupt:
        LOGGER.info("Stopping Activity Controller")
    finally:
        controller.request_shutdown()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1.0)
        worker = controller.worker
        if worker is not None:
            worker.join(timeout=2.0)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    config = replace(
        CONFIG,
        intensity=args.intensity,
        dry_run=CONFIG.dry_run or args.dry_run,
    )

    if config.enable_text_cursor_clicking and not AS.AXIsProcessTrusted():
        LOGGER.warning(
            "Accessibility permission is not granted; editable-text detection and "
            "global hotkeys may not work. Check System Settings > Privacy & Security."
        )

    if args.headless:
        return run_headless(config)

    try:
        return run_web_gui(config)
    except Exception as exc:
        LOGGER.exception("Unable to start the local control panel: %s", exc)
        LOGGER.error("Use --headless to run without the control panel.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
