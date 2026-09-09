# Activity Controller

A macOS desktop activity simulator with a local browser control panel and a
terminal-only mode. It can randomly move the mouse, scroll, switch applications
with Command+Tab, navigate with Tab, and click editable text fields.

Suggested script filename: `activity_controller.py`. The current entry point is
`script.py`, as used in the examples below.

## Setup

Requires macOS and Python 3.10 or newer. From this directory, create a virtual
environment and install the dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pyautogui pynput pyobjc-framework-ApplicationServices
```

Grant Accessibility permission to the terminal or IDE running the script in
macOS System Settings → Privacy & Security → Accessibility. The script uses
macOS accessibility APIs to detect editable text fields and global hotkeys to
pause or stop activity.

## Usage

Open the browser control panel:

```sh
python script.py
```

The panel starts in the **Ready** state. Choose the activity options and click
**Start**. The server listens on `127.0.0.1` using an automatically assigned port;
its URL is printed in the terminal if the browser does not open automatically.

Preview actions in the terminal without sending mouse or keyboard input:

```sh
python script.py --headless --dry-run
```

Run activity immediately in terminal-only mode at low intensity:

```sh
python script.py --headless --intensity low
```

| Option | Description |
| --- | --- |
| `--intensity LEVEL` | `very_low`, `low`, `medium` (default), `high`, or `very_high`. |
| `--dry-run` | Log intended actions without sending mouse or keyboard input. Works with either interface. |
| `--headless` | Start the automation immediately without the browser panel. Still requires a macOS desktop session. |

## Controls

- **Ctrl+1:** pause or resume activity.
- **Ctrl+2:** stop activity. In browser mode, the controller remains available to restart it.
- **Screen corner:** move the pointer to a screen corner to trigger PyAutoGUI's emergency fail-safe when it next checks for input.
- **Ctrl+C:** exit from the terminal.
- **Stop and close controller:** stop activity and shut down the browser controller.

Closing the browser tab alone does not stop the script.

## Configuration

The browser panel lets you change intensity and activity toggles while running.
By default, mouse movement, scrolling, application switching, and editable-text
clicking are enabled; Tab navigation is disabled.

To change startup defaults or advanced settings, edit `ActivityConfig` and
`CONFIG` in `script.py`. Edit `INTENSITY_SETTINGS` to adjust timing and action
ranges. Browser setting changes are kept in memory and do not persist after exit.

Editable-text clicking checks macOS accessibility roles and skips fields
identified as secure. Live mode sends real input to your desktop; use
`--dry-run` to inspect the activity first.
