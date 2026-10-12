# Flow Studio – Complete Design Guide

Redesign of "Google Flow — Autonomous Image-to-Video Batch Suite". Companion to `flow-studio-redesign.html` (interactive mockup with light, dark and auto modes).

## 1. What the app does (as read from your screenshot)

1. You load a **script** (`.md`) containing **prompt pairs**.
2. Each pair has **Step 1**: an image prompt, and **Step 2**: a video prompt applied to that image.
3. The app drives Google Flow in a browser: sign in, calibrate button positions, generate image, then video.
4. Finished scripts move to `scripts/completed/` and the next script starts automatically (8 videos per script).
5. Logs show progress. There is no download feature yet.

## 2. Problems in the current UI

| Problem | Why it hurts |
|---|---|
| Everything is on one screen | Setup, settings, queue, prompts and logs compete for attention |
| Setup buttons are in a flat row of 6 | Users can't tell the order (login, calibrate, test) or what is optional |
| "Action Guide" box takes a full row | Help sits far from the button it explains |
| Settings are always open and technical | URLs and timeouts are rarely changed but dominate the screen |
| Logs panel is a large black empty area | Wastes about a third of the window |
| Many colours (green, red, blue, purple, orange) | No clear primary action |
| Small, dense text and ALL-CAPS section titles | Hard to scan |
| Checkbox labels are long sentences | Slow to read |

## 3. New structure

A left sidebar with four views, plus a status card that is always visible.

| View | Contains | Replaces |
|---|---|---|
| **Run** | Start/Stop, 3-step Setup, Script picker, auto-advance toggles | Pipeline Actions + Script Queue |
| **Prompts** | Prompt pair list, Add pair, Bulk add, Clear all | Prompt Pairs |
| **Settings** | Connection, Timeouts, Testing, Repair | Engine Settings & Selector Recalibration |
| **Logs** | Simple/Detailed toggle, Copy, Clear, Open file | Logs panel |

**Status card (sidebar, always visible):** Idle/Running indicator, "0 of 8" count, progress bar, active script name.

## 4. Key design decisions

1. **One primary action.** "Start batch" is the only filled blue button on Run. Stop is red and only enabled while running.
2. **Setup is a real sequence, so it is numbered:** Sign in, Calibrate, Test. Step 1 shows a green check once complete. After first setup it can collapse.
3. **Tooltips replace the Action Guide box.** Hover any button and the explanation appears next to it. Keyboard focus should show the same text.
4. **Settings are grouped like macOS System Settings:** label and helper text on the left, control on the right, one row per setting.
5. **Toggles instead of checkboxes** for on/off options, with a short title and a gray helper line.
6. **Prompt pairs show Image prompt → Video prompt side by side,** clamped to 3 lines. Click to expand and edit.
7. **Destructive actions are red text, not red fills.** "Clear all" and "Remove" should ask for confirmation.
8. **Calmer wording:** sentence case, plain verbs. "Browser Login" becomes "Open browser", "Calibrate All" stays but is explained, "Dismiss Modal" becomes "Dismiss popup", "Selector recalibration" becomes "Repair".

## 5. Design tokens

| Token | Light | Dark |
|---|---|---|
| Window background | `#F5F5F7` | `#1C1C1E` |
| Sidebar | `#ECECF0` | `#232326` |
| Card | `#FFFFFF` | `#2C2C2E` |
| Text | `#1D1D1F` | `#F5F5F7` |
| Secondary text | `#6E6E73` | `#A1A1A6` |
| Divider | `#D2D2D7` | `#3A3A3D` |
| Accent | `#0071E3` | `#0A84FF` |
| Success | `#248A3D` | `#30D158` |
| Danger | `#D70015` | `#FF453A` |

**Type:** system UI font (SF Pro on Mac, Segoe UI Variable on Windows). Page title 28 px bold, body 14 px, helper 12–13 px. Monospace only in Logs.
**Shape:** cards 14 px radius, buttons and inputs 8 px, toggles 42×26 px.
**Spacing:** 4 px grid; card rows 14 px vertical padding; page padding 28–32 px.

## 6. Light / dark / auto mode

- Three-way segmented control in the title bar: **Light, Auto, Dark**. Auto follows the operating system.
- Save the choice in your settings file (for example `"theme": "auto"`) and apply it on launch.
- All colours come from the token table, so no screen needs separate styling.

## 7. Implementation notes for your Python app

Your current look suggests Tkinter. Matching this design is difficult there. Recommended order:

1. **Best fit: CustomTkinter** (`pip install customtkinter`). It has built-in light/dark mode (`set_appearance_mode("system")`), rounded buttons, switches and segmented buttons. Use `CTkTabview` or a sidebar frame for the four views.
2. **Alternative: PySide6 (Qt) with a stylesheet.** More control, closer to this mockup. Use `QStackedWidget` for views and a QSS file per theme.
3. **Tooltips:** CustomTkinter needs a small tooltip helper (`Toplevel` shown on `<Enter>`, hidden on `<Leave>`). Qt has `setToolTip()`.
4. **Threading:** run the browser automation in a worker thread and update the status card through a queue, so the window never freezes.
5. **Keep your logic unchanged:** only the view layer changes. Map each old button to the same handler.

## 8. Future features (designed to fit)

- **Downloads:** add a "Results" view in the sidebar showing a grid of finished videos with Download, Open folder and "Download all". Show a badge on the sidebar item when new videos arrive.
- **Per-pair status** in Prompts: waiting, generating, done, failed, with a retry button.
- **Notifications** when a batch finishes (system toast).
- **Estimated time remaining** under the progress bar.
- **Keyboard shortcuts:** Ctrl+Enter start, Esc stop, Ctrl+1–4 switch views.

## 9. Accessibility checklist

- Text contrast at least 4.5:1 in both themes.
- Visible focus ring on every control (blue 2 px outline).
- Never use colour alone: status always has a text label ("Running").
- Minimum click target 32 px tall.
- Respect the OS "reduce motion" setting for the progress animation.

---

## 10. First-run setup ("Start" view)

A new **Start** item sits at the top of the sidebar, above Run. It opens automatically on a new install and carries a blue "New" badge until setup is finished.

### How the app decides it is a new install
On every launch, before showing the main window, check the folder next to the script:

```python
from pathlib import Path
BASE = Path(__file__).parent
needs_setup = (
    not (BASE / "chrome_profile").exists()
    or not (BASE / "selectors.json").exists()
    or not config.get("setup_complete", False)
)
# True  -> open the Start view
# False -> open the Run view
```
Create `scripts/` and `scripts/completed/` automatically if they are missing. Save `"setup_complete": true` in your config when the last step finishes.

### The five screens
| Step | Screen | What happens |
|---|---|---|
| 1 | **Welcome** | One sentence on what the app does, a preview of the 3 tasks, and a "Get started" button. |
| 2 | **Checking this computer** | Scans for the app folder, scripts folder and `chrome_profile`. Shows Found / Not found. If no profile exists it says "This looks like a new install" and moves on. |
| 3 | **Sign in to Google Flow** | One large "Sign in with Google" button opens the browser using the `chrome_profile` folder. When the Flow page loads, show "Signed in". |
| 4 | **Teach the app Flow** | One "Start calibration" button runs your existing Calibrate All. Shows progress (for example "3 of 6 controls"). |
| 5 | **You're all set** | Summary and a "Go to Run" button. |

Rules: one decision per screen, one blue button, a Back link, and no technical words. A returning user can reopen the Start view any time to redo sign-in or calibration.

## 11. Overview panel (right side)

A wider panel (330 px) that summarizes the app at a glance. Each group is its own rounded card in the style of Apple's System Settings.

**Anatomy of a card**
- A 40 px rounded icon tile with a soft gradient: blue (Prompts), purple (Script), orange (Folders), gray (Settings).
- A small gray label and a large 20 px semibold value, for example "8 pairs" or "dynamite-script.md".
- A pill button on the right ("Edit" or "Change") that jumps to the matching view.
- Detail rows below, 14 px text with a thin divider: label on the left, value in gray on the right.

| Card | Headline | Rows | Links to |
|---|---|---|---|
| **Prompts** | 8 pairs | Each pair makes 1 image + 1 video; Format 9:16 vertical | Prompts |
| **Script** | Active script name | Scripts waiting; What happens when finished | Run |
| **Folders** | 3 locations | Scripts, Finished, Sign-in status | Settings |
| **Settings** | Default | Image timeout, Video timeout, Test mode | Settings |

The Sign-in row reads "Not set up" until the Start screens are finished, then shows `chrome_profile`. The panel is never hidden. Below about 1160 px it narrows to 280 px, and below about 900 px it moves under the main view.

## 12. Files in this package

| File | Purpose |
|---|---|
| `flow-studio-redesign.html` | Interactive mockup: light/dark/auto, first-run Start screens, all four views, overview panel |
| `flow-studio-redesign-spec.md` / this guide | Written explanation of every decision |

Try the mockup in this order: walk through Start, press Go to Run, press Start batch, then check Logs, then switch themes.

---

## 13. Revision 3: Setup, live Run, Scripts & Prompts, Settings

This section **replaces sections 3, 10 and 11 wherever they disagree.**

### New sidebar
| Item | Purpose | Shown when |
|---|---|---|
| **Setup** | One-time sign-in and calibration | Always. Shows a "Required" badge until your logic reports setup complete |
| **Run** | Start/stop and watch progress | Always |
| **Scripts & Prompts** | Everything about what gets generated | Always |
| **Settings** | How the app talks to Flow, timing, errors, advanced | Always |
| **Logs** | Plain-language activity history | Always |

The old sidebar status card ("Idle", "0 of 8") is removed. Progress now lives on the Run screen.

### Setup
- Renamed from "Start". The five-step wizard runs on a new install.
- When your logic detects setup is complete, the wizard is replaced by a **Setup complete** summary with **Redo sign-in** and **Recalibrate** buttons. The "Required" badge disappears.
- The Setup card is **removed from Run**. Run now only runs.

### Run (live progress)
Top to bottom:
1. **Header:** script name, **Start batch** (becomes **Resume batch** after a stop) and **Stop**.
2. **Now card:** status pill (Ready, Running, Needs your attention, Paused, Complete), a large "2 of 8 videos" count with a progress bar, then the **current pair**: its title, its image prompt, a 9:16 thumbnail once the image exists, and a two-stage tracker **1 Image → 2 Video** (Waiting, In progress, Done, Rejected, Skipped).
3. **Error banner** (red, inside the Now card): for example "Policy violation on pair 2 (image)". It explains what happened, reassures that progress is saved, and offers **Retry**, **Edit prompt** (jumps to Scripts & Prompts) and **Skip pair**.
4. **All pairs:** one row per pair with a status chip (Waiting, Making image, Making video, Done, Image rejected, Skipped).
5. **Saved progress:** one row per script with its saved state, for example "5 of 8 done · pair 6 stopped: policy violation", with a **Resume** button, an issue chip, or "Complete". This is where your save-state logic is shown.

**Data your logic needs to supply to the UI**
| Field | Example |
|---|---|
| Script name | `dynamite-script.md` |
| Videos done / total | 2 / 8 |
| Current pair index and title | 2, "Warehouse explosion aftermath" |
| Stage status per pair | image: waiting / working / done / error / skipped; same for video |
| Current image prompt and thumbnail path | text + `.png` |
| Error object | `{pair, stage, code: "policy_violation", message}` |
| Saved states | list of `{script, done, total, skipped, last_error}` |

Suggested error codes and plain-language messages: `policy_violation` ("Flow declined this prompt"), `timeout` ("Flow took too long"), `ui_changed` ("Flow looks different. Recalibrate"), `signed_out` ("Please sign in again").

### Scripts & Prompts (formerly Prompts)
| Card | Contents |
|---|---|
| **How scripts work** | Three steps: Add (paste .md files in the folder), Choose, Run |
| **Scripts folder** | The folder path, **Open folder**, **Browse…**, the active-script picker with **Load** and **Refresh** |
| **Script behavior** | Auto-start next script, move finished scripts to "completed", videos per script (8), video format (9:16 or 16:9) |
| **Prompt pairs** | Add pair, Bulk add, Clear all, then each pair with its image and video prompt |

### Settings
Grouped by what the user is trying to do:
| Group | Settings |
|---|---|
| **Google Flow** | Flow address, project canvas, saved sign-in folder, show/hide browser window |
| **Timing** | Image timeout, video timeout, pause between pairs |
| **Errors** | What to do when a prompt is rejected (Ask me / Skip / Stop), retries per step, save progress automatically |
| **Advanced** | Reload project before each pair, test mode, recalibrate a single control, view selectors |

Settings marked as additions (**show browser window, pause between pairs, on-reject behavior, retries, videos per script, video format**) are placeholders for options your logic may already have. Keep the ones that match your code and delete the rest.

### Right-hand overview panel
Unchanged in design. The first card is now called **Scripts & prompts**, and its Edit/Change buttons go to the Scripts & Prompts screen.
