# Google Flow Image-to-Video Automation — Project Status & Handover

**Date:** October 9, 2026  
**Status:** In Progress — Ready for Next Session  
**Active Repository:** `F:\I-TO-V Tool`

---

## 1. Executive Summary
This document provides a comprehensive log of all work completed, technical architecture decisions, identified bugs, the user's latest requirements from voice notes, and the remaining roadmap so work can resume immediately without any lost context.

---

## 2. What We Accomplished (Completed Features)

### A. Core Architecture & Profile Isolation
- **Persistent Profile:** Configured Playwright Chromium to launch with a dedicated persistent profile (`chrome_profile`), eliminating the need to copy Google Chrome profile files or deal with lock conflicts.
- **Human Emulation Delays:** Implemented 3.0-second delay rules across all critical DOM interactions in `flow_core.py` (typing prompts, clicking generate, waiting for canvas settling, clicking thumbnails, etc.).

### B. Script Queue & Automation System
- **Script Management:** Built `scripts/` directory for active scripts and `scripts/completed/` for auto-archiving.
- **Script Parser (`import_script.py`):** Automatically parses markdown scripts (e.g., `brandy-script.md`) into image and video prompt pairs, automatically handling scenes and formatting.
- **GUI Script Manager (`app.py`):**
  - Script selector combobox.
  - "Load Selected Script" and "Browse File..." buttons.
  - Live output directory tracking (`output/<script_slug>/`).
  - Completed video counter (e.g., `Completed: 1/8 videos`).
  - Checkbox to automatically move finished scripts to `scripts/completed/`.

### C. Live Calibration & Inspection Tools
- **In-Browser Pause/Resume:** Injected interactive draggable floating widget into Google Flow during calibration with `Alt+P` keyboard shortcut.
- **Quick Single-Step Recalibration:** Added a dedicated UI section in `app.py` allowing the user to select and recalibrate any **single selector** (e.g., just `video_mode_menu` or `project_more_options`) without having to repeat the other 14 steps.
- **Selectors View:** Added a button to inspect and edit `selectors.json` directly.

### D. Card-Scoped Menu & Project Toolbar Exclusion (Option 1)
- **Problem Solved:** Google Flow has two identical `button[aria-label="More options"]`:
  1. The top project/canvas toolbar button (`flow-more-options-menu`).
  2. The image card's 3-dot button on the canvas.
  Earlier code clicked the first one, opening the project menu instead of the image menu.
- **Solution Implemented:**
  - Card-scoped search: locates the 3-dot button strictly inside the image tile's ancestor container (`flow-image-card`, `flow-media-card`, `flow-node`).
  - Excluded project header: added `is_project_header_element()` which strictly excludes any button inside `flow-more-options-menu`, `header`, `mat-toolbar`, `flow-project-header`, or the top 75px of the viewport.
  - Added optional `project_more_options` calibration step so the automation knows the exact project header button to ignore.
  - Abandoned right-click (which opened Chrome's native context menu) and pixel-proximity (which was fragile on resize/minimize).

### E. Pointer Interception & Modal Dismissal Fixes
- **`force=True` on Hover/Click:** Fixed Playwright 30-second lockup (`"intercepts pointer events"`) by using `force=True` and short timeouts (`4000ms`), plus dispatching native JavaScript `mouseover`/`mouseenter` events.
- **Smart Modal Return (`close_image_viewer`):** When images are downloaded, automatically attempts the calibrated back button, fallback close buttons (`arrow_back`, `close`), and presses the `Escape` key twice to guarantee the canvas is visible.

---

## 3. What the User Asked & Latest Bug Reports (Voice Notes Analysis)

In the two latest voice messages, the user reported two specific bugs and requested a new testing feature:

### Bug A: Image Generation Wait Loop Times Out (120s) Even When Image is Already Ready
- **User's Report:**
  > *"It's still waiting 10s, 20s, 30s, 40s, 50s, 60s... on generation, but the image is ALREADY generated and calculated. But the agent is still in thinking format... It says image reached limit, but two images ready."*
- **Root Cause Identified:**
  In `flow_core.py`, `is_generation_in_progress(page)` was searching the **entire document** for strings like `"Generating"`, `"Creating"`, or any `mat-progress-bar` / `mat-spinner`.
  In Google Flow, the bottom prompt bar or an unrelated component retains a "Thinking / Generating" state or background spinner, causing `is_generation_in_progress` to return `True` for the full 120 seconds even though the new image tile was already rendered on the canvas 50 seconds earlier.
- **Solution Required:**
  Remove the global document-wide spinner/text check. Base readiness strictly on the newly appeared card:
  1. Check if `now_count > before`.
  2. Check if the newly created `img` is complete and loaded (`img.complete && img.naturalWidth > 100`).
  3. Check that the *card itself* has no active spinner. Once that card's image is loaded, proceed immediately without waiting for global text indicators.

### Bug B: Image Viewer Not Closing ("Didn't click on back")
- **User's Report:**
  > *"It didn't click on back. It didn't click the back option, so it automatically restarted the whole thing."*
- **Root Cause & Fix:**
  If `download_images` is checked, clicking the thumbnail opens the full-screen image editor. If the back button fails, the editor stays open, blocks the canvas, and causes the next step to fail.
  - If the user doesn't need to download images, thumbnail opening should be skipped entirely.
  - If downloading, `close_image_viewer` must aggressively dismiss the modal (via calibrated selector and `Escape` key) and verify the canvas is returned before touching `video_mode_menu`.

### Feature Request: Test Mode / Skip Steps (Avoid Generating 50+ Images)
- **User's Request:**
  > *"For testing right now, I need buttons where I can skip options... I have like 50 images generated with testing, so what should I do? We should add a Test Mode where I can easily skip steps to test if that step works or not without waiting the whole process."*
- **Solution to Implement:**
  Add a **Test Mode / Step Execution Mode** in `app.py`:
  1. **"Skip Image Generation (Use Existing Image on Canvas)"** checkbox:
     Allows testing the Image-to-Video pipeline directly without waiting 1-2 minutes for a new image to generate.
  2. **Individual Step Test Buttons:**
     - `[Test: Open Card 3-Dots & Click Video Mode]`
     - `[Test: Video Prompt & Generate]`
     - `[Test: Download Video]`
     This allows testing and verifying any single phase in 3 seconds.

---

## 4. Current Configuration State

### `selectors.json` (Latest Calibrated Snapshot)
```json
{
  "image_prompt_box": "div.ProseMirror",
  "image_generate": "button[aria-label=\"Start generation\"]",
  "image_result": "img.image",
  "image_download_menu": "button[aria-label=\"Finished editing\"]",
  "video_mode": "button:has-text(\"Add to prompt\")",
  "video_prompt_box": "div.ProseMirror",
  "video_generate": "button[aria-label=\"Start generation\"]",
  "video_result": "img.thumbnail",
  "image_back_to_menu": "button[aria-label=\"Finished editing\"]",
  "video_mode_menu": "div:nth-of-type(2) > div > flow-image-hotbar > flow-hotbar-container > div > button:nth-of-type(3)",
  "video_download_menu": "button[aria-label=\"Download media\"]",
  "video_download_menu2": "button:has-text(\"1080p Upscaled\")",
  "video_download": "button[aria-label=\"Done editing scene\"]",
  "project_more_options": "div:nth-of-type(2) > div:nth-of-type(3) > div > div > flow-more-options-menu > button"
}
```

### `settings.json`
- `image_timeout`: `120` seconds
- `video_timeout`: `120` seconds
- `newest_tile`: `"first"`
- `reload_each_pair`: `true`
- `skip_image_gen`: `false` (or `true` in test mode)
- `download_images`: `true`

---

## 5. Implementations Completed (Summary)

1. **✓ Universal Visual Highlighter & 3-Second Interaction Delays:**
   - Every click (`click()`, `click_loc()`) and text entry (`fill()`) draws a high-contrast glowing red outline (`4px solid #ef4444`, `box-shadow: 0 0 25px 8px #ef4444`) around the targeted element.
   - Includes a 1.0s pre-click delay so the user can visually verify the target, and a 3.0s post-click delay so animations and state transitions settle cleanly.

2. **✓ Card 3-Dots Menu Fixed (Never Clicks Image Thumbnail):**
   - Removed `tile.click()` from `open_image_context_menu()` so Google Flow's full-screen viewer is never opened when intending to access options.
   - Hovers the card tile container to trigger `<flow-image-hotbar>`.
   - Locates and clicks button #3 / More options on the active hotbar using the calibrated selector and hotbar queries.
   - Clicks `button:has-text("Add to prompt")` directly with highlight and 3s delay.

3. **✓ Restored Clean Image Generation & Selection (Zero Stop-Button Side Effects):**
   - Completely reverted `label == 'image'` in `is_tile_ready` to the simple, working logic: monitors the card for progress bars/spinners and image load completion (`img.complete && img.naturalWidth > 50`).
   - Removed any global or Stop button checks that were causing premature exits during agent prompt parsing.

4. **✓ Test Mode & Dynamic Reload:**
   - Added `[x] 🧪 Test Mode: Skip Image Gen` checkbox in GUI.
   - Added `[🧪 Test: Open 3-Dots & Click Video Mode]` button for instant testing.
   - Added automatic module reload on every task launch.

5. **✓ Video Generation Readiness (Scoped Strictly to Video Card):**
   - Enforces `min_generation_s = 60s` to prevent false exits at 25s–30s.
   - Monitors the target video card: while rendering, progress bars (`mat-progress-bar`, `[role="progressbar"]`, etc.) and generating text keep it waiting.
   - Once render completes (~120s–150s), the disappearance of spinners and presence of play indicators (top-left circle badge, `mat-icon: play_arrow`, SVG) triggers completion without waiting for the 360s timeout.
   - Fully supports retries/rerenders where tile counts remain unchanged.

6. **✓ Fixed Download & Browser Disconnect Recovery:**
   - In `download()`: waits for `download_obj.save_as(dest)` to completely stream and save the MP4 to disk before closing the editor overlay.
   - Fallback to `downloads/` directory copy if direct `save_as()` encounters stream closure timing.
   - Uses `Escape` key fallback if overlay close button locator fails or is detached.

7. **✓ Download Crash Root Cause Resolved & 'Skip Download' Mode Added:**
   - **Root Cause Identified:** Minidump analysis revealed crash `0xc0000005` (Access Violation) in `chrome.dll` at offset `0x29c7ca`. The Windows low-integrity sandbox blocked `chrome.exe` under user AppData with `Access is denied (0x5)` when spawning child processes for file download handling.
   - **Fix 1 (Sandbox & Download Flags):** Added `--no-sandbox`, `--disable-setuid-sandbox`, and explicit `downloads_path` to Chromium persistent context launch.
   - **Fix 2 ('Skip Download' GUI Toggle):** Added `[ ] Download videos (MP4)` checkbox in Settings (`download_videos` in `settings.json`). When unchecked, automation generates image and video on canvas, detects completion in ~84s, and immediately moves to the next pair without opening overlays or triggering downloads.
   - **Fix 3 (Browser Auto-Relaunch Recovery):** Added `get_healthy_page()` in `run_batch`. If Chromium or the persistent context is ever terminated or closed, the batch runner automatically relaunches Chromium fresh, navigates back to the project, and resumes subsequent pairs seamlessly without cascading failures.

8. **✓ Complete Download Removal & Autonomous Batch Queue Suite:**
   - **Download Logic Completely Removed:** Stripped out all video/image file downloads, 1080p cloud upscaling triggers, and overlay interactions. Flow generation is verified directly on the canvas (~84s per video).
   - **`video_generated` Tracking Variable:** Tracks completed videos per active script (e.g., `8 / 8`).
   - **Autonomous Script Queue & Auto-Archive:** Once all prompt videos for a script are generated, the script is automatically moved to `scripts/completed/`, the queue refreshes, and the next pending `.md` script from `scripts/` is loaded and executed automatically until all scripts are finished.

9. **✓ UX Polish: Dynamic Hover Explanations, Large Prompt Typography & Dual Log Modes:**
   - **Dynamic Hover Action Guide:** Removed static subtitles from underneath action buttons. Added a prominent, high-contrast Action Guide card with larger font (`10.5pt / 11pt`) that dynamically updates with detailed instructions whenever the user hovers over any button.
   - **Large Prompt Typography:** Increased prompt textarea font to `11pt` Segoe UI with expanded 4-line editing height and clearer step headers.
   - **Easy Logs vs Detailed Logs Toggle:** Added instant mode switching:
     - `[📄 Easy Logs]`: Human-friendly high-level milestones ("Batch started", "Image prompt entered", "Image completed", "Video prompt entered", "Video completed", "Pair 1/8 finished", "Script moved to completed/").
     - `[🔍 Detailed Logs]`: Full technical stream (selector polling, counts, elapsed timings, DOM traces).

10. **✓ Flow Studio Complete Redesign (CustomTkinter 3-Column Architecture):**
    - **Design Reference:** Implemented 1:1 match with `UI Changes/Flow Studio – Redesign.html` and `UI Changes/flow-studio-complete-guide.md`.
    - **Appearance & Tokens:** Added Light / Auto / Dark theme segmented switcher in the top bar with native CustomTkinter appearance mode switching and token colors (`#F5F5F7` / `#1C1C1E`, `#ECECF0` / `#232326`, `#FFFFFF` / `#2C2C2E`, `#0071E3` / `#0A84FF`).
    - **Navigation Sidebar (230px):**
      - Navigation tabs: `Start` (with "New" badge on fresh installs), `Run`, `Prompts` (with pair count badge), `Settings`, `Logs`.
      - Persistent Status Card: Status dot ("Idle" / "Running" / "Paused"), `0 of 8` large metric, smooth progress bar, active script name.
    - **Right Overview Inspector (320px):**
      - Apple System Settings style rounded cards with colored icon tiles (Prompts, Script, Folders, Settings) and quick-action jump links.
    - **Full 5 Views:**
      1. `Start`: 5-step onboarding wizard with computer scanning, Chrome sign-in check, calibration wizard, and summary.
      2. `Run`: Clean header with `Start batch` and `Stop`, 1-2-3 Setup sequence (Sign in, Calibrate, Test), Script queue picker with auto-advance and archive switches.
      3. `Prompts`: Side-by-side prompt cards with 11pt typography, `Add pair`, `Bulk add…`, and `Clear all`.
      4. `Settings`: Grouped cards for Connection, Timeouts, Testing toggles, and Repair.
      5. `Logs`: Segmented toggle for `Simple` vs `Detailed` modes, Copy, Clear, Open file, and real-time console.
    - **GSD Integration:** Tracked and planned via `.planning/STATE.md` and `.planning/phases/01-flow-studio-ui-redesign/PLAN.md`.

---
*All files verified and compiled with Python syntax checks passing (exit code 0).*

---

### Update: Tkinter Callback TclError Fix & Pre-flight Auto-Check

1. **Root Cause of Crash:**
   - In `_finish_wz()`, `badge.destroy()` was called without nullifying or removing the badge reference in `self.nav_btns["start"]`.
   - When transitioning via `self.switch_view("run")`, `badge.configure()` was called on the destroyed Tk label widget, raising `_tkinter.TclError: invalid command name ".!ctkframe2.!ctkframe.!ctkframe.!ctkframe.!ctklabel.!label"`.
2. **Resolution:**
   - Updated `self.nav_btns` to store `(btn_frame, btn, badge)`.
   - Added guards `if badge and badge.winfo_exists():` and `if btn_f.winfo_manager() != "pack": continue` across `switch_view()`.
   - Implemented `self.show_start_nav(False)` to cleanly unmap the Start navigation button using `pack_forget()`.
3. **Startup Environment Pre-Flight Auto-Check:**
   - Implemented `check_setup_status()`:
     - Verifies `chrome_profile` exists and contains files.
     - Verifies `selectors.json` exists with all 9 required selectors calibrated.
     - Verifies `scripts/` folder exists.
   - **When Fully Configured (Default on this machine):**
     - Completely hides the `Start` option from the sidebar.
     - Launches directly into the `Run` view without prompting onboarding.
   - **When Setup Incomplete / Fresh Install:**
     - Displays `Start` with an amber warning badge (`⚠ Setup`).
     - Shows an actionable Warning Banner at the top of the Start tab with a warning button (`⚠ Fix Missing Item`) jumping directly to the incomplete step.
     - Shows a warning card on the Run tab.
     - Guards `do_start()` to prevent batch execution until required components are ready.

---

### Update: Policy Violation Handling & Persistent Session Resume

1. **Policy Violation Detection & Dedicated File Logging:**
   - Real-time DOM inspection via `detect_policy_violation(page)` continuously scans Google Flow for policy violation banners, toasts, and flagged status cards during generation.
   - Raises `PolicyViolationError`, immediately aborting the 360s wait timeout.
   - Logs the violation in `logs/policy_violations.json`, `logs/policy_violations.txt`, and per-script `output/<script_slug>/policy_violations.json`/`.txt`.
   - Records: timestamp, script name, pair number, stage (`image` vs `video`), exact error text, image prompt, and video prompt.
   - Automatically advances to the next prompt pair without halting the batch queue.
   - Added a **"Policy warnings"** button in the Logs view for instant inspection.

2. **Persistent Batch State & "Resume from Last Stand":**
   - Automatically updates `batch_state.json` on disk: records script path, standing pair index, total pairs, completed pairs list, and execution status (`running`, `stopped`, `interrupted`, `completed`).
   - If the user presses "Stop" or if the app/browser is closed or crashes, the exact pair number where the agent stopped is preserved.
   - **Interactive Resume Card:** Appears on the Run view displaying:
     - `🔄 Unfinished Batch: <script_name>` (Standing at Pair #X of Y)
     - `▶ Resume from Pair #X`: Skips previously completed pairs and resumes directly from pair #X.
     - `↺ Start Fresh (Pair #1)`: Resets state to start from the beginning.
     - `Dismiss`: Hides the banner.
   - **Smart `do_start()` Detection:** When clicking "Start batch", prompts the user with an intuitive Yes/No/Cancel dialog if an unfinished session is found.

3. **Complete Feature Catalogue:**
   - Created comprehensive documentation file [`FEATURES_LIST.md`](file:///f:/I-TO-V%20Tool/FEATURES_LIST.md) detailing all 10 feature areas, architecture specifications, and capability matrices.




