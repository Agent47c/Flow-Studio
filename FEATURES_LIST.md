# Flow Studio — Complete Feature List & Capability Catalogue

> **Project:** Flow Studio (Google Flow Image-to-Video Batch Automation Suite)  
> **Status:** Fully Operational  
> **Documentation Version:** 1.2  
> **Last Updated:** October 11, 2026  

---

## Executive Overview
Flow Studio is a desktop automation suite engineered for high-throughput batch generation of images and videos on **Google Flow** (labs.google/fx/tools/flow). It features an Apple macOS-inspired design built on CustomTkinter, automated queue processing, real-time safety policy moderation handling, and persistent session recovery.

---

## 1. User Interface & Design System (Apple-Inspired 3-Column Architecture)
- **3-Column Professional Layout:**
  - **Left Sidebar (230px):** Navigation between views, persistent queue status metrics, progress bar, and active script display.
  - **Center View Container (1fr):** Houses the 5 core application views (`Start`, `Run`, `Prompts`, `Settings`, `Logs`) with smooth zero-flicker view swapping.
  - **Right Overview Inspector (320px):** Always-visible diagnostic summary with 4 live cards (`Prompts`, `Script`, `Folders`, `Settings`) and quick-jump action shortcuts.
- **Segmented Appearance Mode Controller:**
  - Top header toggle with **Light**, **Auto** (System Sync), and **Dark** modes.
  - Uses native CustomTkinter color tokens with glassmorphic cards, rounded pills, and high-contrast typography (`Segoe UI Variable`).
- **Interactive Tooltips (`CTkToolTip`):**
  - Robust child-aware hover tooltips across all primary buttons (`Start batch`, `Stop`, `Test video`, `Open browser`, `Calibrate all`, etc.) explaining exact functionality.
  - Features 250ms hover debounce, child-widget event synchronization, instant dismiss on mouse departure, instant dismiss on button click, unmap, or destruction, and auto-dismissal if mouse touches the tooltip popup itself (zero lingering or sticky tooltips).

---

## 2. Startup Environment Auto-Check & Smart Onboarding
- **Pre-Flight Environment Detection (`check_setup_status`):**
  - Automatically verifies `chrome_profile` directory, session files, `selectors.json` (all 9 required selectors), `scripts/` folder, and `output/` directory on launch.
- **Dynamic Start Tab Visibility:**
  - **Configured State (Ready):** The `Start` tab is **completely hidden** from the sidebar; the application lands directly on the **`Run`** view for zero-friction workflows.
  - **Missing Prerequisites State:** Displays the `Start` tab in the sidebar with an amber warning badge (`⚠ Setup`).
- **Actionable Warning Banners:**
  - When setup is missing, a prominent Warning Card is rendered at the top of the Start view and Run view detailing missing items with a **`⚠ Fix Missing Item`** shortcut button that jumps straight to the required step.
- **5-Step Onboarding Wizard:**
  - Step 0: Welcome and feature summary.
  - Step 1: Deep scan of local machine folders.
  - Step 2: One-click Google account login session recorder.
  - Step 3: Interactive UI button calibration wizard.
  - Step 4: Completion verification + "Go to Run" (with crash-guarded transitions).
- **On-Demand Re-entry:**
  - Users can re-launch the Setup Wizard anytime from **Settings → Repair → Setup wizard**.

---

## 3. Persistent Batch State, Token Protection & "Resume from Last Stand"
- **Automatic State Recording (`batch_state.json` & `logs/script_states/<stem>_state.json`):**
  - Continuously records the exact standing state of the batch automation to disk:
    - Active script file and name
    - Current prompt pair index (e.g. Pair #3 of 8)
    - Total pairs count
    - Completed pair indices (`completed_pairs: [1, 2, 3]`)
    - Detailed failed/skipped prompt records (`failed_pairs: [{pair, stage, reason, timestamp}]`)
    - Policy violation logs
    - Status (`"running"`, `"stopped"`, `"interrupted"`, `"completed"`, `"completed_with_errors"`)
    - Output directory and timestamp
- **Token Protection Guarantee (Skip Completed Pairs):**
  - Whenever a script starts, resumes, or reloads, the engine cross-references `completed_pairs` from disk.
  - Any previously completed prompt pair is automatically skipped (`⏩ Pair #X was already completed. Skipping to save tokens.`), guaranteeing zero wasted tokens on re-generation.
- **Non-Blocking Failure Handling & Immediate Prompt Skip:**
  - If a prompt encounters a Google Flow policy violation or exhausts retry attempts, it is immediately logged to `failed_pairs` and disk state, and skipped to allow subsequent pairs to proceed without pipeline stall or abort.
- **Queue Infinite-Loop Prevention:**
  - In-session tracking (`processed_scripts_in_session`) prevents any script with failed or skipped prompts from being re-queued in an infinite loop in the same run, protecting tokens and avoiding runaway execution.
  - Script failure summaries are generated into `logs/script_states/<stem>_failures.txt`.
- **Resume Batch Card on Run View:**
  - When an interrupted or user-stopped batch is detected, an actionable green Resume Card appears above the Setup controls:
    - **`▶ Resume from Pair #X`**: Displays total completed and skipped count, resuming directly from the standing pair.
    - **`↺ Start Fresh (Pair #1)`**: Clears previous state and restarts generation from the beginning.
    - **`Dismiss`**: Hides the card without losing disk history.
- **Smart Launch Prompting in `do_start()`:**
  - If the user clicks "Start batch" directly while an unfinished session is saved, an interactive confirmation dialog asks whether they want to **Resume** from the standing pair or **Start Fresh**.
- **Crash & Stop Resiliency:**
  - If the user presses "Stop" or if the browser process crashes/closes unexpectedly, the exact pair number where the agent stopped is preserved.

---

## 4. Policy Violation Detection & Dedicated File Logging
- **Real-Time Safety & Policy Violation Detection (`detect_policy_violation`):**
  - Actively scans Google Flow's DOM on every 2-second polling tick for toast alerts, snackbars, banners, and error tiles containing policy or safety violation notices (`"policy"`, `"violation"`, `"safety"`, `"guidelines"`, `"harmful"`, `"blocked"`, `"flagged"`).
- **Zero-Hang Fast Recovery:**
  - Prevents the 360-second video timeout freeze: as soon as a prompt is flagged by Google Flow, generation immediately halts, raises `PolicyViolationError`, logs the event, and advances to the next pair in the queue.
- **Persistent Policy Logs (`.json` and `.txt`):**
  - Every violation is recorded with timestamp, script name, pair index, stage (`image` vs `video`), exact error text, image prompt, and video prompt.
  - Saved to global log files: `logs/policy_violations.json` and `logs/policy_violations.txt`.
  - Saved to project-specific output directory: `output/<script_slug>/policy_violations.json` and `policy_violations.txt`.
- **One-Click Policy Log Viewer:**
  - Direct button in the **Logs** view header: **`Policy warnings`** opens the human-readable text log file in one click.

---

## 5. Queue Management & Markdown Script Ingestion
- **Automated Queue Folder Processing (`scripts/`):**
  - Monitors the `scripts/` directory for `.md` and `.txt` prompt files.
  - Dropdown selector allows switching active scripts dynamically.
  - Automatically loads prompt pairs and synchronizes the output folder path (`output/<script_slug>/`).
- **Auto-Advance Queue:**
  - When enabled, automatically loads and processes the next pending script in the queue once the current script completes.
- **Automatic Archival (`scripts/completed/`):**
  - When enabled, moves successfully processed scripts into `scripts/completed/` to prevent duplicate processing.
- **Custom Markdown Parser (`import_script.py`):**
  - Extracts prompt pairs from raw screenplay, storyboard, or structured markdown text with support for numbered headings and prompt blocks.

---

## 6. Prompt Pair Editor & Bulk Import Modal
- **Side-by-Side Prompt Pair Cards:**
  - Visual cards pairing the **Image Prompt** on the left with the corresponding **Video Prompt** on the right.
  - Dynamic pair numbers (`Pair #1`, `Pair #2`, etc.) with individual `Remove` buttons.
- **Bulk Add Modal:**
  - Split multi-line text input allowing users to paste full lists of Image Prompts and Video Prompts simultaneously, automatically matching them 1:1.
- **Prompt Validation:**
  - Checks for non-empty pairs prior to batch execution, alerting users if an image prompt is missing a video prompt or vice-versa.

---

## 7. Google Flow Automation Engine (`flow_core.py`)
- **Single-Thread Playwright Chromium Worker:**
  - Thread-safe background execution isolating Playwright's sync API from Tkinter's main event loop.
- **Project URL Sticky Isolation:**
  - Supports designated project URLs (`project_url`) to work directly inside an existing Google Flow project.
  - Automatically ignores top project header buttons so canvas three-dot menus are never misidentified.
- **Interactive Calibration System:**
  - Guides user through teaching the app where buttons are located on Google Flow (`image_prompt_box`, `image_generate`, `image_result`, `video_mode_menu`, `video_mode`, `video_prompt_box`, `video_generate`, `video_result`).
  - Injected JavaScript widget with **Alt+P Hotkey** and **Pause / Resume** button for complex navigation.
- **Single-Control Recalibration:**
  - Dropdown in **Settings → Repair** allowing users to recalibrate any single button without redoing the entire wizard.
- **Automatic Browser Disconnect Recovery (`get_healthy_page`):**
  - Detects closed or disconnected browser targets and reconnects to the project canvas automatically.

---

## 8. Real-Time Diagnostics & Dual-Mode Logging Console
- **Dual-Mode Filtering Toggle:**
  - **`Simple` Mode:** Filters out repetitive DOM polling chatter and selector diagnostic notices, displaying only clean, plain-English progress (`✓ Video generated!`, `🎬 PROCESSING SCRIPT`, `⚠️ [POLICY VIOLATION]`, `⏹ Stopped`).
  - **`Detailed` Mode:** Displays complete raw logs including tile counts, DOM candidate selectors, bounding box checks, and Playwright traces.
- **Console Controls:**
  - **`Copy`**: Copies all visible log entries to clipboard.
  - **`Clear`**: Clears the console screen.
  - **`Open file`**: Opens the active log directory in Windows Explorer.
  - **`Policy warnings`**: Opens the safety moderation audit log.

---

## Feature Matrix Summary Table

| Category | Feature Name | Description | Status |
| :--- | :--- | :--- | :--- |
| **UI** | 3-Column macOS Architecture | Sidebar + Center Views + Right Overview Inspector | ✅ Complete |
| **UI** | Segmented Theme Controller | Light / Auto / Dark appearance switcher | ✅ Complete |
| **UI** | Setup View & Complete Screen | 5-step wizard when needed; "Setup complete" screen with Redo sign-in & Recalibrate | ✅ Complete |
| **UI** | Live Run "Now Card" | Status pill, big count headline, progress bar, 9:16 thumbnail preview, 1 Image → 2 Video pipeline | ✅ Complete |
| **UI** | Interactive Error Banner | Policy violation banner inside Now Card with Retry, Edit prompt, and Skip pair | ✅ Complete |
| **UI** | All Pairs Card | List of all script pairs with status chips (Waiting, Making image, Making video, Done, Rejected, Skipped) | ✅ Complete |
| **UI** | Saved Progress Card | Active script progress with Resume button, plus historical states from disk | ✅ Complete |
| **UI** | Scripts & Prompts View | 3-column "How scripts work", Scripts folder picker, Script behavior options, and Prompt pairs | ✅ Complete |
| **UI** | Grouped Settings | Google Flow, Timing, Errors (On reject action, Retries, Auto-save), Advanced groups | ✅ Complete |
| **State** | Persistent State Saving | Saves standing pair index and status to `batch_state.json` and `logs/script_states/` | ✅ Complete |
| **State** | Token Protection Guarantee | Skips already completed pairs automatically (`⏩ Pair #X was already completed`) | ✅ Complete |
| **Moderation**| Policy Violation Detection | Real-time DOM inspection for Google Flow safety blocks | ✅ Complete |
| **Moderation**| Configurable Reject Action | "Ask me", "Skip the pair", or "Stop the batch" on safety violation | ✅ Complete |
| **Moderation**| Policy Violation Logs | Stores records in `logs/` and `output/<script>/` (`.json` + `.txt`) | ✅ Complete |
| **Queue** | Script Queue Watcher | Auto-detects `.md` files in `scripts/` directory | ✅ Complete |
| **Queue** | Auto-Advance Queue | Advances to next script when active script completes | ✅ Complete |
| **Queue** | Completed Scripts Archival | Automatically moves finished scripts to `completed/` | ✅ Complete |
| **Queue** | Infinite-Loop Prevention | In-session deduplication prevents re-running failed scripts | ✅ Complete |
| **UI** | Dedicated Calibrate Tab | First-class view for 8-step calibration, health score, and 9-control individual recalibration | ✅ Complete |
| **Engine** | Single-Control Recalibration | Select and recalibrate individual control buttons directly from Calibrate tab | ✅ Complete |
| **Engine** | Canvas Controls Verification | `test_all_selectors` tests mapped selectors against active Flow canvas without running a batch | ✅ Complete |
| **Engine** | Clean Browser Closure Handling | Playwright `TargetClosedError` & unhandled Promise catch guards for zero-traceback exits | ✅ Complete |
| **Engine** | Zero-False-Rejection Generation | Removed premature 1.5s checks and global canvas locks; generation verified via target tile rendering | ✅ Complete |
| **Engine** | Session State Restoration | Automatic restoration of standing script, pair index, and completed/failed states across restarts | ✅ Complete |
| **UI** | Crash-Proof Alert Hierarchy | Permanent `alert_container` and `view_container` separation eliminating `_tkinter.TclError` | ✅ Complete |
| **UI** | Prominent Resume Controls | Dedicated `▶ Resume batch` and `↺ Start fresh` controls inside Now Card and Header | ✅ Complete |
| **UI** | Prompt Failure Inspector Modal | Interactive modal displaying full error details with editable prompts and 1-click load into editor | ✅ Complete |
| **Engine** | Headless Toggle | `show_browser_window` setting for background operation | ✅ Complete |
| **Engine** | Rate-Limit Protection | Configurable `pause_between_pairs` delay | ✅ Complete |
| **Logs** | Dual-Mode Log Filter | Simple (plain language) vs Detailed (raw DOM) view | ✅ Complete |
| **Logs** | Policy Warnings Viewer | Quick-open button for policy violation records | ✅ Complete |

