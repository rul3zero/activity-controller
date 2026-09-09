# Paper

A small macOS menu bar app with a plain-text notes editor and desktop input tools.
Paper can move the mouse, scroll, switch applications with Command+Tab, navigate
with Tab, and click editable text fields. It stays in the menu bar when you close
the browser and starts **Ready**, with desktop input stopped.

## Use the built app

1. Open `dist/Paper.app`, or drag it to **Applications** and open it there.
2. Look for the **pencil icon** in the menu bar at the top of your screen. Paper
   does not show a Dock icon.
3. Hover over the pencil to see its status and localhost URL. Click it to see
   the clickable URL, **Open Editor & Controls**, **Copy Localhost Link**,
   **Start**, **Pause/Resume**, **Stop**, and **Quit Paper**.
4. Open the editor, choose your desktop tools and intensity, then click **Start**.
   The editor also supports writing, importing text, saving, and exporting a note.
5. Closing the browser keeps Paper running. Use **Stop** to stop input while
   keeping the app available, or **Quit Paper** to shut down everything.

The usual address is `http://127.0.0.1:8765/`. If that port is busy, Paper chooses
a free one and shows the actual URL in the menu, tooltip, page header, and log.
The server only accepts connections from this Mac.

## First-time setup from source

### 1. Check Python and Git

Open **Terminal** from Applications → Utilities, then run:

```sh
python3 --version
git --version
```

Use Python 3.10 or newer. If needed, install Python from
[Python.org](https://www.python.org/downloads/macos/).
If Git is missing, install Apple's Command Line Tools and wait for it to finish:

```sh
xcode-select --install
```

### 2. Download the project

```sh
cd ~/Documents
git clone https://github.com/rul3zero/activity-controller.git
cd activity-controller
```

If you already have the project, open that existing folder in Terminal.
The repository URL retains its original name; the app is named Paper.

### 3. Install dependencies

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run all remaining commands in the project folder with this environment active.

### 4. Preview without controlling your desktop

```sh
python main.py --dry-run --open
```

The menu bar app and editor open. Click **Start** to preview; the panel shows
**PREVIEW** and actions are logged without sending mouse or keyboard input.
Dry run does not install global hotkeys; use the menu or web buttons to stop.
Quit Paper before switching to live mode.

### 5. Allow macOS permissions

For real desktop input:

1. Open **System Settings → Privacy & Security → Accessibility**.
2. Enable **Paper** when using the packaged app. Click **+** and select
   `Paper.app` if it is missing.
3. When running Python from Terminal, iTerm, or an IDE, enable that host app
   instead, along with any executable macOS explicitly requests.
4. Check **Privacy & Security → Input Monitoring** if global hotkeys do not work,
   and enable the app macOS requests.
5. Quit and reopen the app after changing permissions.

Paper's menu includes shortcuts to both settings pages. Live input cannot start
until Accessibility permission is granted. Permission errors and worker errors
are shown in the editor. No `chmod` or `sudo` command is needed to run
`python main.py`.

See Apple's guides for
[Accessibility](https://support.apple.com/en-gb/guide/mac-help/-mh43185/mac)
and [Input Monitoring](https://support.apple.com/guide/mac-help/control-access-to-input-monitoring-on-mac-mchl4cedafb6/mac).

### 6. Run Paper

```sh
python main.py
```

Click the pencil in the menu bar to open the editor. Source mode needs its
Terminal process to remain running; build the app below to launch independently
of Terminal.

## Build a standalone Mac app

Install the build tools **in the same virtual environment**, then build:

```sh
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm Paper.spec
open dist/Paper.app
```

The result is **dist/Paper.app**. Copy that whole app to Applications. Python is
included in the bundle, so the installed app does not need the source folder or
virtual environment. Quit an existing Paper instance before rebuilding or testing
an updated version.

`Paper.spec` includes the web page, pencil icon, macOS input backends, and
`LSUIElement` so the app runs in the menu bar. Keep the spec and
`assets/Paper.icns` in Git; build outputs are ignored. To regenerate the icon:

```sh
python tools/build_icon.py
```

The build targets the architecture of the Python interpreter used to build it.
This Mac's build is Apple Silicon (arm64). Distribution to other Macs may require
a separate architecture build and Apple Developer ID signing/notarization; this
project currently makes a local, ad-hoc signed app. See
[PyInstaller's macOS bundle options](https://pyinstaller.org/en/stable/spec-files.html#spec-file-options-for-a-macos-bundle).

## Controls and options

| Control | Action |
| --- | --- |
| Start | Begin the selected desktop input actions. |
| Pause / Resume | Suspend or resume input. |
| Stop | Stop input; Paper stays available for a new session. |
| Ctrl+1 | Pause/resume during live input. |
| Ctrl+2 | Stop live input. |
| Screen corner | Trigger PyAutoGUI's fail-safe on its next input check. |
| Quit Paper | Stop input and exit the menu bar and server. |
| Command+S in the editor | Save the current note. |

| Command | Behavior |
| --- | --- |
| `python main.py` | Start in the menu bar, initially idle. |
| `python main.py --open` | Also open the editor in your browser. |
| `python main.py --dry-run --open` | Preview actions without sending input. |
| `python main.py --web` | Browser-only interface, without a menu bar icon. |
| `python main.py --port 9000` | Prefer a different localhost port. |
| `python main.py --headless --dry-run` | Start a terminal preview immediately; Ctrl+C exits. |
| `python main.py --headless --intensity low` | Start live terminal input immediately. |

Intensity values: `very_low`, `low`, `medium`, `high`, `very_high`.
The last saved intensity and toggles are restored at launch. Opening a second
instance opens the existing instance's editor.

## Notes, preferences, and logs

Paper stores its files in `~/Library/Application Support/Paper/`:

- `note.txt`: your note, automatically saved after editing; **Export** saves a copy.
- `settings.json`: desktop tool preferences.
- `paper.log`: rotating diagnostic logs, including preview actions.
- `instance.json`: the running app's localhost address.

Notes persist across restarts and localhost port changes. Use one editor tab at
a time when editing the note; the latest saved copy wins. Wait for **Saved on this
Mac** before quitting from the menu bar. The page warns before closing with
unsaved changes. Import replaces the current note after confirmation.

Mouse movement, scrolling, window switching, and editable-text clicking start
enabled; Tab navigation starts disabled. Editable-text detection skips fields
identified as secure. Live mode sends real desktop input.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No module named PyInstaller` | Activate `.venv` and install `requirements-dev.txt`. Use the capitalization `python -m PyInstaller`. |
| No Dock icon or browser window | Paper lives in the menu bar; click the pencil icon. |
| Menu icon not visible | Check hidden menu bar icons or free space near the MacBook notch. |
| Desktop input fails | Grant Accessibility to Paper or your terminal, then reopen it. |
| Hotkeys do not work | Check Input Monitoring; web and menu controls remain available. Hotkeys are disabled in preview mode. |
| Browser says disconnected | Open the current URL from Paper's menu; the port may have changed. |
| App quits or cannot start | Read `~/Library/Application Support/Paper/paper.log`. |
| Rebuilt app still behaves like the previous version | Quit the old instance first, replace the app, reopen, and recheck permissions. |
| No input after Start | Check **LIVE/PREVIEW**, enabled tools, and any displayed error. |

## Development checks

Tests exercise lifecycle controls, interruption, saved data, single-instance
behavior, request validation, and loopback endpoints without sending desktop input.

```sh
python -m unittest discover -s tests -v
```

For an isolated manual preview with separate notes and settings:

```sh
PAPER_DATA_DIR="$PWD/build/preview" python main.py --dry-run --open --port 0
```
