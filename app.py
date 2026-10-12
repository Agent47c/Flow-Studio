"""Flow Studio — Autonomous Image-to-Video Batch Suite.
Built with CustomTkinter according to the design specification in 'UI Changes/Flow Studio – Redesign (1).html'
and 'UI Changes/flow-studio-complete-guide (1).md' (Revision 3).
"""
import json
import os
import queue
import re
import shutil
import threading
import time
import traceback
from itertools import zip_longest
from pathlib import Path
from tkinter import filedialog, messagebox

# pyrefly: ignore [missing-import]
import customtkinter as ctk

import flow_core as core

SETTINGS_FILE = core.APP_DIR / "settings.json"

# =====================================================================
# DESIGN SYSTEM TOKENS (Light, Dark)
# =====================================================================
TOKEN_WIN = ("#F5F5F7", "#1C1C1E")
TOKEN_SIDE = ("#ECECF0", "#232326")
TOKEN_CARD = ("#FFFFFF", "#2C2C2E")
TOKEN_TEXT = ("#1D1D1F", "#F5F5F7")
TOKEN_SUB = ("#6E6E73", "#A1A1A6")
TOKEN_LINE = ("#D2D2D7", "#3A3A3D")
TOKEN_FILL = ("#F0F0F3", "#3A3A3C")
TOKEN_ACC = ("#0071E3", "#0A84FF")
TOKEN_ACC_HOVER = ("#005BB5", "#0071E3")
TOKEN_OK = ("#248A3D", "#30D158")
TOKEN_WARN = ("#B45309", "#F59E0B")
TOKEN_WARN_HOVER = ("#92400E", "#D97706")
TOKEN_BAD = ("#D70015", "#FF453A")
TOKEN_BAD_HOVER = ("#B20011", "#D70015")


# =====================================================================
# TOOLTIP HELPER
# =====================================================================
class CTkToolTip:
    """Robust tooltip helper shown on hover and immediately dismissed when mouse moves away or clicks."""

    def __init__(self, widget, text, delay_ms=250):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tip_window = None
        self._show_job = None
        self._hide_job = None

        self._bind_targets()

    def _bind_targets(self):
        targets = [self.widget]
        try:
            if hasattr(self.widget, "winfo_children"):
                targets.extend(self.widget.winfo_children())
        except Exception:
            pass
        for t in targets:
            try:
                t.bind("<Enter>", self._on_enter, add="+")
                t.bind("<Leave>", self._on_leave, add="+")
                t.bind("<ButtonPress>", self._on_click, add="+")
                t.bind("<Destroy>", self._on_destroy, add="+")
                t.bind("<Unmap>", self._on_destroy, add="+")
            except Exception:
                pass

    def _on_enter(self, event=None):
        if self._hide_job:
            try:
                self.widget.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None
        if not self.text or self.tip_window:
            return
        self._cancel_show()
        try:
            self._show_job = self.widget.after(self.delay_ms, self.show_tip)
        except Exception:
            pass

    def _on_leave(self, event=None):
        self._cancel_show()
        if self._hide_job:
            try:
                self.widget.after_cancel(self._hide_job)
            except Exception:
                pass
        try:
            self._hide_job = self.widget.after(70, self.hide_tip)
        except Exception:
            self.hide_tip()

    def _on_click(self, event=None):
        self._cancel_show()
        self.hide_tip()

    def _on_destroy(self, event=None):
        self._cancel_show()
        self.hide_tip()

    def _cancel_show(self):
        if self._show_job:
            try:
                self.widget.after_cancel(self._show_job)
            except Exception:
                pass
            self._show_job = None

    def show_tip(self):
        self._show_job = None
        if self.tip_window or not self.text:
            return
        try:
            if not self.widget.winfo_exists():
                return

            wx = self.widget.winfo_rootx()
            wy = self.widget.winfo_rooty()
            ww = self.widget.winfo_width()
            wh = self.widget.winfo_height()

            x = wx + (ww // 2) - 90
            y = wy + wh + 6
            screen_w = self.widget.winfo_screenwidth()
            if x + 280 > screen_w:
                x = screen_w - 290
            if x < 10:
                x = 10

            import tkinter as tk
            self.tip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tw.attributes("-topmost", True)

            tw.bind("<Enter>", lambda e: self.hide_tip(), add="+")
            tw.bind("<Leave>", lambda e: self.hide_tip(), add="+")
            tw.bind("<ButtonPress>", lambda e: self.hide_tip(), add="+")

            frame = ctk.CTkFrame(
                tw,
                fg_color=("#1D1D1F", "#2C2C2E"),
                border_color=TOKEN_LINE,
                border_width=1,
                corner_radius=8,
            )
            frame.pack()
            frame.bind("<Enter>", lambda e: self.hide_tip(), add="+")

            lbl = ctk.CTkLabel(
                frame,
                text=self.text,
                font=("Segoe UI Variable", 12),
                text_color=("#F5F5F7", "#F5F5F7"),
                wraplength=260,
                padx=10,
                pady=6,
            )
            lbl.pack()
            lbl.bind("<Enter>", lambda e: self.hide_tip(), add="+")
        except Exception:
            self.hide_tip()

    def hide_tip(self, event=None):
        self._cancel_show()
        if self._hide_job:
            try:
                self.widget.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None


# =====================================================================
# THREAD-SAFE UI BRIDGE
# =====================================================================
class UI:
    """Bridge between the worker thread and the GUI."""

    def __init__(self, app):
        self.app = app
        self.stop = threading.Event()
        self.skip = threading.Event()
        self.paused = threading.Event()
        self.user_decision = queue.Queue()

    def log(self, msg):
        self.app.q.put(("log", msg))

    def step(self, msg, show_skip):
        self.app.q.put(("step", (msg, show_skip)))

    def set_pause_state(self, is_paused):
        self.app.q.put(("pause_state", is_paused))

    def queue_progress(self, script_name, video_gen, total_pairs, pending_count):
        self.app.q.put(("queue_progress", (script_name, video_gen, total_pairs, pending_count)))

    def pair_stage(self, n, stage, status):
        """Notifies GUI of pair stage progress: stage in ('image', 'video'), status in ('wait', 'work', 'ok', 'err', 'skip')."""
        self.app.q.put(("pair_stage", (n, stage, status)))

    def pair_error(self, script_name, n, total_pairs, stage, code, message):
        """Notifies GUI of pair error / policy violation."""
        self.app.q.put(("pair_error", (script_name, n, total_pairs, stage, code, message)))

    def ask_decision(self, n, stage, message):
        """Blocks worker thread until user decides in GUI ('retry', 'skip', 'stop')."""
        self.user_decision = queue.Queue()
        self.app.q.put(("ask_decision", (n, stage, message)))
        while not self.stop.is_set():
            try:
                return self.user_decision.get(timeout=0.5)
            except queue.Empty:
                continue
        return "stop"


# =====================================================================
# PROMPT PAIR ROW CARD
# =====================================================================
class PairRow:
    """Prompts view card showing side-by-side Image and Video prompts."""

    def __init__(self, app, parent, index, img="", vid=""):
        self.app = app
        self.index = index
        self.frame = ctk.CTkFrame(
            parent,
            fg_color=TOKEN_CARD,
            border_color=TOKEN_LINE,
            border_width=1,
            corner_radius=12,
        )
        self.frame.pack(fill="x", padx=4, pady=5)

        # Header
        hdr = ctk.CTkFrame(self.frame, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(10, 4))

        self.lbl_title = ctk.CTkLabel(
            hdr,
            text=f"Pair {index}",
            font=("Segoe UI Variable", 13, "bold"),
            text_color=TOKEN_TEXT,
        )
        self.lbl_title.pack(side="left")

        btn_remove = ctk.CTkButton(
            hdr,
            text="Remove",
            width=64,
            height=26,
            corner_radius=6,
            fg_color="transparent",
            text_color=TOKEN_BAD,
            hover_color=TOKEN_FILL,
            font=("Segoe UI Variable", 12, "bold"),
            command=lambda: app.remove_row(self),
        )
        btn_remove.pack(side="right")
        CTkToolTip(btn_remove, f"Removes Pair {index} from this script.")

        # Side-by-side prompt columns
        cols = ctk.CTkFrame(self.frame, fg_color="transparent")
        cols.pack(fill="x", padx=14, pady=(2, 12))
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)

        # Left: Image prompt
        c0 = ctk.CTkFrame(cols, fg_color=TOKEN_FILL, corner_radius=8)
        c0.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(
            c0,
            text="Image prompt",
            font=("Segoe UI Variable", 11, "bold"),
            text_color=TOKEN_SUB,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 2))
        self.img = ctk.CTkTextbox(
            c0,
            height=78,
            wrap="word",
            fg_color="transparent",
            text_color=TOKEN_TEXT,
            font=("Segoe UI Variable", 12),
        )
        self.img.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self.img.insert("1.0", img)
        self.img.bind("<KeyRelease>", lambda e=None: self.app.on_prompt_edited())

        # Right: Video prompt
        c1 = ctk.CTkFrame(cols, fg_color=TOKEN_FILL, corner_radius=8)
        c1.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(
            c1,
            text="Video prompt",
            font=("Segoe UI Variable", 11, "bold"),
            text_color=TOKEN_SUB,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 2))
        self.vid = ctk.CTkTextbox(
            c1,
            height=78,
            wrap="word",
            fg_color="transparent",
            text_color=TOKEN_TEXT,
            font=("Segoe UI Variable", 12),
        )
        self.vid.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self.vid.insert("1.0", vid)
        self.vid.bind("<KeyRelease>", lambda e=None: self.app.on_prompt_edited())

    def get(self):
        return self.img.get("1.0", "end").strip(), self.vid.get("1.0", "end").strip()

    def get_title(self):
        img_t, _ = self.get()
        if not img_t:
            return f"Prompt Pair {self.index}"
        first_line = img_t.splitlines()[0].strip()
        return first_line[:40] + ("…" if len(first_line) > 40 else "")

    def set_index(self, index):
        self.index = index
        self.lbl_title.configure(text=f"Pair {index}")


# =====================================================================
# FLOW STUDIO MAIN APPLICATION
# =====================================================================
class App:
    def __init__(self, root):
        self.root = root
        root.title("Flow Studio")
        root.geometry("1280x820")
        root.minsize(1080, 680)

        self.q = queue.Queue()
        self.ui = UI(self)
        self.thread = None
        self.rows = []

        # App & Batch State
        self.is_running = False
        self.is_paused = False
        self.batch_started = False
        self.current_pair_idx = 1
        self.video_generated = 0
        self.skipped_count = 0
        self.total_pairs = 8
        self.pending_scripts = 0
        self.active_script_name = "None"
        self.current_script_path = None
        self.current_view = "run"
        self.log_mode = "easy"
        self.all_logs = []
        self.current_error = None

        # Per-pair stage states: pair_index (1-based) -> {"image": "wait"|"work"|"ok"|"err"|"skip", "video": "wait"|"work"|"ok"|"err"|"skip"}
        self.pair_stages = {}

        # Setup wizard state
        self.wz_step = 0
        self.wz_signed = 0
        self.wz_calibrated = 0
        self.vars = {}

        # Load Saved Config
        saved = {}
        if SETTINGS_FILE.exists():
            try:
                saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        self.cfg = {**core.DEFAULTS, **saved.get("cfg", {})}
        for dep in ["download_images", "download_videos", "image_name", "video_name"]:
            self.cfg.pop(dep, None)

        # Theme setting: "light", "dark", or "auto"
        theme_pref = self.cfg.get("theme", "auto").lower()
        if theme_pref == "auto":
            ctk.set_appearance_mode("system")
        elif theme_pref == "light":
            ctk.set_appearance_mode("light")
        else:
            ctk.set_appearance_mode("dark")

        # Directories
        self.scripts_dir = core.APP_DIR / "scripts"
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        (self.scripts_dir / "completed").mkdir(parents=True, exist_ok=True)

        # Check environment and setup readiness before showing views
        self.is_fully_setup, self.missing_setup_items, self.setup_details = self.check_setup_status()
        self.needs_setup = not self.is_fully_setup
        self.current_view = "run" if self.is_fully_setup else "start"

        # Build UI Architecture
        self._build_top_bar()
        self._build_main_layout()

        # Load initial prompt pairs
        self.resume_pair_index = 1
        pairs = saved.get("pairs") or [["", ""]] * 8
        for i, pair in enumerate(pairs, 1):
            self.add_row(pair[0], pair[1])

        self.refresh_scripts_list()
        self.init_pair_stages()
        self.restore_saved_session_state()
        self.update_overview_panel()
        self.render_now_card()
        self.render_all_pairs_card()
        self.render_saved_progress_card()
        self.render_calibrate_view()
        self.render_problems_view()
        self.update_problems_badge()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(150, self.poll)

    # ------------------------------------------------------------- ENVIRONMENT CHECKS & WIZARD
    def check_setup_status(self):
        """Validates whether prerequisites (profile, selectors, scripts, output) exist."""
        missing = []
        details = {}

        prof_name = self.cfg.get("profile_dir", "chrome_profile")
        prof_path = core.APP_DIR / prof_name
        has_profile = prof_path.is_dir() and any(prof_path.iterdir())
        details["profile"] = {
            "ok": has_profile,
            "label": "Chrome Profile",
            "path": str(prof_path),
            "status": "Found" if has_profile else "Missing sign-in",
        }
        if not has_profile:
            missing.append("Google Sign-in profile is missing (chrome_profile)")

        sels = core.load_selectors()
        missing_sels = [k for k in core.REQUIRED if k not in sels]
        has_selectors = core.SELECTORS_FILE.exists() and len(missing_sels) == 0
        details["selectors"] = {
            "ok": has_selectors,
            "label": "Control Selectors",
            "path": str(core.SELECTORS_FILE),
            "status": "All calibrated" if has_selectors else f"{len(missing_sels)} unmapped",
        }
        if not has_selectors:
            missing.append(f"Selectors calibration incomplete ({len(missing_sels)} required buttons not set)")

        scripts_dir = self.scripts_dir
        scripts_count = len(list(scripts_dir.glob("*.md"))) if scripts_dir.is_dir() else 0
        has_scripts = scripts_dir.is_dir()
        details["scripts"] = {
            "ok": has_scripts,
            "label": "Scripts folder",
            "path": str(scripts_dir),
            "status": f"{scripts_count} script(s)" if scripts_count > 0 else "Ready",
        }
        if not has_scripts:
            missing.append("Scripts directory missing")

        out_dir = core.APP_DIR / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        details["output"] = {
            "ok": True,
            "label": "Output folder",
            "path": str(out_dir),
            "status": "Ready",
        }

        is_ready = has_profile and has_selectors
        return is_ready, missing, details

    def reopen_setup_wizard(self, step=0):
        """Navigates to the Setup view, optionally forcing a specific wizard step."""
        self.wz_step = step
        self.switch_view("start")
        self._render_wz_step()

    def _get_first_incomplete_step(self):
        prof_name = self.cfg.get("profile_dir", "chrome_profile")
        prof_path = core.APP_DIR / prof_name
        if not (prof_path.is_dir() and any(prof_path.iterdir())):
            return 2  # Sign in
        sels = core.load_selectors()
        missing_sels = [k for k in core.REQUIRED if k not in sels]
        if missing_sels:
            return 3  # Calibrate
        return 1

    # ------------------------------------------------------------- TOP BAR
    def _build_top_bar(self):
        self.top_bar = ctk.CTkFrame(
            self.root,
            height=42,
            fg_color=TOKEN_SIDE,
            border_color=TOKEN_LINE,
            border_width=1,
            corner_radius=0,
        )
        self.top_bar.pack(fill="x")

        title_lbl = ctk.CTkLabel(
            self.top_bar,
            text="Flow Studio",
            font=("Segoe UI Variable", 13, "bold"),
            text_color=TOKEN_TEXT,
        )
        title_lbl.pack(side="left", padx=16, pady=6)

        # Segmented Theme Toggle (Light | Auto | Dark)
        self.theme_seg = ctk.CTkSegmentedButton(
            self.top_bar,
            values=["Light", "Auto", "Dark"],
            height=26,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            selected_color=TOKEN_CARD,
            selected_hover_color=TOKEN_CARD,
            unselected_color=TOKEN_FILL,
            unselected_hover_color=TOKEN_LINE,
            text_color=TOKEN_TEXT,
            font=("Segoe UI Variable", 11, "bold"),
            command=self.on_theme_changed,
        )
        pref = self.cfg.get("theme", "auto").capitalize()
        self.theme_seg.set(pref if pref in ["Light", "Auto", "Dark"] else "Auto")
        self.theme_seg.pack(side="right", padx=16, pady=6)

    def on_theme_changed(self, mode):
        m = mode.lower()
        if m == "auto":
            ctk.set_appearance_mode("system")
        elif m == "light":
            ctk.set_appearance_mode("light")
        else:
            ctk.set_appearance_mode("dark")
        self.cfg["theme"] = m
        self.save_settings()

    # ------------------------------------------------------------- MAIN 3-COLUMN LAYOUT
    def _build_main_layout(self):
        self.app_frame = ctk.CTkFrame(self.root, fg_color=TOKEN_WIN, corner_radius=0)
        self.app_frame.pack(fill="both", expand=True)

        # 1. Left Sidebar (230px)
        self.sidebar = ctk.CTkFrame(
            self.app_frame,
            width=230,
            fg_color=TOKEN_SIDE,
            border_color=TOKEN_LINE,
            border_width=1,
            corner_radius=0,
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self._build_sidebar()

        # 2. Right Overview Inspector (320px)
        self.inspector = ctk.CTkFrame(
            self.app_frame,
            width=320,
            fg_color=TOKEN_SIDE,
            border_color=TOKEN_LINE,
            border_width=1,
            corner_radius=0,
        )
        self.inspector.pack(side="right", fill="y")
        self.inspector.pack_propagate(False)
        self._build_inspector()

        # 3. Center Main View Container (1fr)
        self.main_container = ctk.CTkFrame(self.app_frame, fg_color=TOKEN_WIN, corner_radius=0)
        self.main_container.pack(side="left", fill="both", expand=True)

        # Permanent top container for alerts/banner (always at top of main_container)
        self.alert_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.alert_container.pack(side="top", fill="x")

        # Container for all views (always below alert_container)
        self.view_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.view_container.pack(side="top", fill="both", expand=True)

        # Alert banner inside alert_container
        self._build_alert_banner()

        # Build Views inside self.view_container
        self.views = {}
        self.views["start"] = self._build_view_start()
        self.views["run"] = self._build_view_run()
        self.views["problems"] = self._build_view_problems()
        self.views["prompts"] = self._build_view_prompts()
        self.views["calibrate"] = self._build_view_calibrate()
        self.views["settings"] = self._build_view_settings()
        self.views["logs"] = self._build_view_logs()

        # Show initial view
        self.switch_view(self.current_view)

    # ------------------------------------------------------------- SIDEBAR
    def _build_sidebar(self):
        nav_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav_box.pack(fill="x", padx=10, pady=16)

        self.nav_btns = {}

        def make_nav(key, label, badge_text="", badge_color=None):
            btn_f = ctk.CTkFrame(nav_box, fg_color="transparent")
            btn_f.pack(fill="x", pady=2)

            btn = ctk.CTkButton(
                btn_f,
                text=label,
                anchor="w",
                height=34,
                corner_radius=8,
                fg_color="transparent",
                text_color=TOKEN_TEXT,
                hover_color=TOKEN_FILL,
                font=("Segoe UI Variable", 13, "bold"),
                command=lambda: self.switch_view(key),
            )
            btn.pack(side="left", fill="x", expand=True)

            badge = None
            if badge_text:
                badge = ctk.CTkLabel(
                    btn_f,
                    text=badge_text,
                    font=("Segoe UI Variable", 10, "bold"),
                    fg_color=badge_color or TOKEN_ACC,
                    text_color="#FFFFFF",
                    corner_radius=6,
                    padx=6,
                    pady=1,
                )
                badge.pack(side="right", padx=6)

            self.nav_btns[key] = (btn_f, btn, badge)

        # In Revision 3: Setup is always present in sidebar. Shows "Required" badge until setup complete.
        req_badge = "Required" if self.needs_setup else ""
        make_nav("start", "Setup", req_badge, badge_color=TOKEN_ACC)
        make_nav("run", "Run")
        make_nav("problems", "Problems")
        make_nav("prompts", "Scripts & Prompts")
        make_nav("calibrate", "Calibrate")
        make_nav("settings", "Settings")
        make_nav("logs", "Logs")

    def switch_view(self, key):
        self.current_view = key
        for k, v in self.views.items():
            if k == key:
                v.pack(fill="both", expand=True)
            else:
                v.pack_forget()

        # Update sidebar active styling
        for k, (btn_f, btn, badge) in self.nav_btns.items():
            if not btn_f.winfo_exists():
                continue
            if k == key:
                btn.configure(fg_color=TOKEN_ACC, text_color="#FFFFFF", hover_color=TOKEN_ACC_HOVER)
                if badge and badge.winfo_exists() and badge.cget("text"):
                    badge.configure(fg_color="#FFFFFF", text_color=TOKEN_ACC[0])
            else:
                btn.configure(fg_color="transparent", text_color=TOKEN_TEXT, hover_color=TOKEN_FILL)
                if badge and badge.winfo_exists() and badge.cget("text"):
                    badge.configure(fg_color=TOKEN_BAD if k == "problems" else TOKEN_ACC, text_color="#FFFFFF")

        if key == "start":
            self._render_wz_step()
        elif key == "run":
            self.render_now_card()
            self.render_all_pairs_card()
            self.render_saved_progress_card()
        elif key == "problems":
            self.render_problems_view()
        elif key == "calibrate":
            self.render_calibrate_view()

        self.update_overview_panel()

    # ------------------------------------------------------------- RIGHT OVERVIEW INSPECTOR
    def _build_inspector(self):
        lbl = ctk.CTkLabel(
            self.inspector,
            text="Overview",
            font=("Segoe UI Variable", 13, "bold"),
            text_color=TOKEN_SUB,
            anchor="w",
        )
        lbl.pack(fill="x", padx=14, pady=(16, 6))

        self.insp_cards = {}

        def make_card(key, glyph, icon_bg, label, headline, action_lbl, action_cmd, rows):
            card = ctk.CTkFrame(
                self.inspector,
                fg_color=TOKEN_CARD,
                border_color=TOKEN_LINE,
                border_width=1,
                corner_radius=14,
            )
            card.pack(fill="x", padx=12, pady=5)

            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.pack(fill="x", padx=12, pady=(10, 4))

            tile = ctk.CTkFrame(hdr, width=36, height=36, corner_radius=10, fg_color=icon_bg)
            tile.pack(side="left")
            tile.pack_propagate(False)
            ctk.CTkLabel(tile, text=glyph, font=("Segoe UI", 15), text_color="#FFFFFF").pack(expand=True)

            titles = ctk.CTkFrame(hdr, fg_color="transparent")
            titles.pack(side="left", padx=10, fill="x", expand=True)
            ctk.CTkLabel(titles, text=label, font=("Segoe UI Variable", 11), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
            lbl_hd = ctk.CTkLabel(titles, text=headline, font=("Segoe UI Variable", 15, "bold"), text_color=TOKEN_TEXT, anchor="w")
            lbl_hd.pack(fill="x")

            btn = ctk.CTkButton(
                hdr,
                text=action_lbl,
                width=50,
                height=24,
                corner_radius=12,
                fg_color=TOKEN_FILL,
                text_color=TOKEN_ACC,
                hover_color=TOKEN_LINE,
                font=("Segoe UI Variable", 11, "bold"),
                command=action_cmd,
            )
            btn.pack(side="right")

            row_lbls = []
            for l_txt, r_txt in rows:
                rf = ctk.CTkFrame(card, fg_color="transparent", height=22)
                rf.pack(fill="x", padx=12, pady=2)
                ctk.CTkLabel(rf, text=l_txt, font=("Segoe UI Variable", 12), text_color=TOKEN_TEXT, anchor="w").pack(side="left")
                rl = ctk.CTkLabel(rf, text=r_txt, font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="e")
                rl.pack(side="right")
                row_lbls.append(rl)

            ctk.CTkFrame(card, height=6, fg_color="transparent").pack()
            self.insp_cards[key] = (lbl_hd, row_lbls)

        # 1. Scripts & Prompts Card
        make_card(
            "prompts", "💬", ("#0071E3", "#0A84FF"), "Scripts & prompts", "8 pairs", "Edit",
            lambda: self.switch_view("prompts"),
            [("Each pair makes", "1 image + 1 video"), ("Auto-advance", "Enabled")]
        )
        # 2. Script Card
        make_card(
            "script", "📄", ("#8E4EC6", "#AF52DE"), "Script", "None", "Change",
            lambda: self.switch_view("prompts"),
            [("Waiting", "0 scripts"), ("When finished", "Starts next one")]
        )
        # 3. Folders Card
        make_card(
            "folders", "📁", ("#FF9500", "#FF9F0A"), "Folders", "3 locations", "Edit",
            lambda: self.switch_view("prompts"),
            [("Scripts", "scripts/"), ("Finished", "scripts/completed/"), ("Sign-in", "Not set up")]
        )
        # 4. Settings Card
        make_card(
            "settings", "⚙", ("#8E8E93", "#636366"), "Settings", "Default", "Edit",
            lambda: self.switch_view("settings"),
            [("Image timeout", "120 s"), ("Video timeout", "360 s"), ("Test mode", "Off")]
        )

    def update_overview_panel(self):
        if not hasattr(self, "insp_cards") or not self.insp_cards:
            return

        # Prompts
        hd_p, rows_p = self.insp_cards["prompts"]
        hd_p.configure(text=f"{len(self.rows)} pairs")
        adv = self.auto_advance_var.get() if hasattr(self, "auto_advance_var") else True
        rows_p[1].configure(text="Auto-advance On" if adv else "Single script")

        # Script
        hd_s, rows_s = self.insp_cards["script"]
        s_name = self.current_script_path.name if self.current_script_path else "None"
        hd_s.configure(text=s_name if len(s_name) < 22 else s_name[:19] + "…")
        rows_s[0].configure(text=f"{self.pending_scripts} scripts")
        adv = self.auto_advance_var.get() if hasattr(self, "auto_advance_var") else True
        rows_s[1].configure(text="Starts next one" if adv else "Stops")

        # Folders
        hd_f, rows_f = self.insp_cards["folders"]
        prof = (core.APP_DIR / "chrome_profile").exists()
        rows_f[2].configure(text="chrome_profile" if prof else "Not set up")

        # Settings
        hd_set, rows_set = self.insp_cards["settings"]
        img_t = self.vars["image_timeout"].get() if "image_timeout" in self.vars else "120"
        vid_t = self.vars["video_timeout"].get() if "video_timeout" in self.vars else "360"
        t_mode = "On" if hasattr(self, "skip_image_gen") and self.skip_image_gen.get() else "Off"
        rows_set[0].configure(text=f"{img_t} s")
        rows_set[1].configure(text=f"{vid_t} s")
        rows_set[2].configure(text=t_mode)

    # ------------------------------------------------------------- ALERT BANNER (CALIBRATION)
    def _build_alert_banner(self):
        self.alert_frame = ctk.CTkFrame(
            self.alert_container,
            fg_color=("#FFFBEB", "#2A2314"),
            border_color=("#F59E0B", "#B45309"),
            border_width=1,
            corner_radius=10,
        )
        self.step_lbl = ctk.CTkLabel(
            self.alert_frame,
            text="",
            font=("Segoe UI Variable", 12, "bold"),
            text_color=("#92400E", "#FDE68A"),
            wraplength=640,
            justify="left",
            anchor="w",
        )
        self.step_lbl.pack(side="left", padx=14, pady=8, fill="x", expand=True)

        self.skip_btn = ctk.CTkButton(
            self.alert_frame,
            text="Skip step",
            width=80,
            height=28,
            corner_radius=6,
            fg_color=("#D97706", "#B45309"),
            text_color="#FFFFFF",
            font=("Segoe UI Variable", 11, "bold"),
            command=self.ui.skip.set,
        )
        self.pause_calib_btn = ctk.CTkButton(
            self.alert_frame,
            text="Pause",
            width=70,
            height=28,
            corner_radius=6,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            font=("Segoe UI Variable", 11, "bold"),
            command=self.toggle_pause_calib,
        )

    # ------------------------------------------------------------- VIEW 1: SETUP
    def _build_view_start(self):
        view = ctk.CTkFrame(self.view_container, fg_color="transparent")
        self.wz_container = ctk.CTkFrame(view, fg_color="transparent", width=520)
        self.wz_container.pack(expand=True, pady=30)
        return view

    def _render_wz_step(self):
        for w in self.wz_container.winfo_children():
            w.destroy()

        # If already set up, show the "Setup complete" screen as specified in Revision 3
        if not self.needs_setup:
            self._render_setup_complete_screen()
            return

        s = self.wz_step

        # Step Dots Indicator (5 dots)
        dots = ctk.CTkFrame(self.wz_container, fg_color="transparent")
        dots.pack(pady=(0, 20))
        for i in range(5):
            d_col = TOKEN_ACC if i <= s else TOKEN_LINE
            d = ctk.CTkFrame(dots, width=8, height=8, corner_radius=4, fg_color=d_col)
            d.pack(side="left", padx=4)

        # Step 0: Welcome
        if s == 0:
            tile = ctk.CTkFrame(self.wz_container, width=76, height=76, corner_radius=19, fg_color=TOKEN_ACC)
            tile.pack(pady=(0, 20))
            tile.pack_propagate(False)
            ctk.CTkLabel(tile, text="▶", font=("Segoe UI", 28), text_color="#FFFFFF").pack(expand=True)

            ctk.CTkLabel(self.wz_container, text="Welcome to Flow Studio", font=("Segoe UI Variable", 28, "bold"), text_color=TOKEN_TEXT).pack()
            ctk.CTkLabel(self.wz_container, text="Turn written prompts into finished videos, automatically. Setup takes about three minutes.",
                         font=("Segoe UI Variable", 14), text_color=TOKEN_SUB, wraplength=480).pack(pady=(6, 20))

            card = ctk.CTkFrame(self.wz_container, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
            card.pack(fill="x", pady=(0, 24))

            def add_wz_row(parent, title, sub):
                rf = ctk.CTkFrame(parent, fg_color="transparent")
                rf.pack(fill="x", padx=16, pady=10)
                ctk.CTkLabel(rf, text=title, font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
                ctk.CTkLabel(rf, text=sub, font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")

            add_wz_row(card, "Check this computer", "Look for your folders and saved sign-in.")
            add_wz_row(card, "Sign in to Google Flow", "You only do this once.")
            add_wz_row(card, "Teach the app Flow", "So it knows where to click.")

            btn = ctk.CTkButton(self.wz_container, text="Get started", height=42, corner_radius=10, fg_color=TOKEN_ACC,
                                text_color="#FFFFFF", font=("Segoe UI Variable", 14, "bold"), command=lambda: self._set_wz_step(1))
            btn.pack(fill="x", pady=4)

        # Step 1: Checking computer
        elif s == 1:
            ctk.CTkLabel(self.wz_container, text="Checking this computer", font=("Segoe UI Variable", 26, "bold"), text_color=TOKEN_TEXT).pack()
            ctk.CTkLabel(self.wz_container, text="Looking for folders next to the app.", font=("Segoe UI Variable", 14), text_color=TOKEN_SUB).pack(pady=(6, 20))

            card = ctk.CTkFrame(self.wz_container, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
            card.pack(fill="x", pady=(0, 20))

            def check_row(parent, title, sub, ok, status_text):
                rf = ctk.CTkFrame(parent, fg_color="transparent")
                rf.pack(fill="x", padx=16, pady=10)
                left = ctk.CTkFrame(rf, fg_color="transparent")
                left.pack(side="left")
                ctk.CTkLabel(left, text=title, font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
                ctk.CTkLabel(left, text=sub, font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
                ctk.CTkLabel(rf, text=status_text, font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_OK if ok else ("#F59E0B", "#FBBF24")).pack(side="right")

            check_row(card, "App folder", "Found at " + str(core.APP_DIR.name), True, "Found")
            s_count = len(list(self.scripts_dir.glob("*.md")))
            check_row(card, "Scripts folder", f"{s_count} scripts ready to run", True, f"{s_count} scripts")
            prof_found = (core.APP_DIR / "chrome_profile").exists() and any((core.APP_DIR / "chrome_profile").iterdir())
            check_row(card, "Saved sign-in (chrome_profile)", "Chrome profile folder", prof_found, "Found" if prof_found else "Not found")

            btn = ctk.CTkButton(self.wz_container, text="Continue", height=40, corner_radius=10, fg_color=TOKEN_ACC,
                                text_color="#FFFFFF", font=("Segoe UI Variable", 14, "bold"), command=lambda: self._set_wz_step(2))
            btn.pack(fill="x", pady=4)
            ctk.CTkButton(self.wz_container, text="Back", height=28, fg_color="transparent", text_color=TOKEN_SUB,
                          font=("Segoe UI Variable", 12), command=lambda: self._set_wz_step(0)).pack()

        # Step 2: Sign in
        elif s == 2:
            ctk.CTkLabel(self.wz_container, text="Sign in to Google Flow", font=("Segoe UI Variable", 26, "bold"), text_color=TOKEN_TEXT).pack()
            ctk.CTkLabel(self.wz_container, text="A browser window will open. Sign in as you normally would. Your password is never stored by this app.",
                         font=("Segoe UI Variable", 14), text_color=TOKEN_SUB, wraplength=480).pack(pady=(6, 20))

            card = ctk.CTkFrame(self.wz_container, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
            card.pack(fill="x", pady=(0, 20), padx=10)

            prof_exists = (core.APP_DIR / "chrome_profile").exists() and any((core.APP_DIR / "chrome_profile").iterdir())
            if self.wz_signed or prof_exists:
                ctk.CTkLabel(card, text="✓ Signed in", font=("Segoe UI Variable", 17, "bold"), text_color=TOKEN_OK).pack(pady=(18, 4))
                ctk.CTkLabel(card, text="Saved to chrome_profile. You won't need to do this again.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB).pack(pady=(0, 18))
            else:
                btn_si = ctk.CTkButton(card, text="Sign in with Google", height=40, corner_radius=8, fg_color=TOKEN_ACC,
                                       text_color="#FFFFFF", font=("Segoe UI Variable", 13, "bold"), command=self._wz_do_signin)
                btn_si.pack(pady=24, padx=20)

            btn = ctk.CTkButton(self.wz_container, text="Continue", height=40, corner_radius=10, fg_color=TOKEN_ACC,
                                text_color="#FFFFFF", font=("Segoe UI Variable", 14, "bold"), command=lambda: self._set_wz_step(3))
            btn.pack(fill="x", pady=4)
            ctk.CTkButton(self.wz_container, text="Back", height=28, fg_color="transparent", text_color=TOKEN_SUB,
                          font=("Segoe UI Variable", 12), command=lambda: self._set_wz_step(1)).pack()

        # Step 3: Calibrate
        elif s == 3:
            ctk.CTkLabel(self.wz_container, text="Teach the app Flow", font=("Segoe UI Variable", 26, "bold"), text_color=TOKEN_TEXT).pack()
            ctk.CTkLabel(self.wz_container, text="The app will click through Flow once to learn where each button is. Keep the browser window visible.",
                         font=("Segoe UI Variable", 14), text_color=TOKEN_SUB, wraplength=480).pack(pady=(6, 20))

            card = ctk.CTkFrame(self.wz_container, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
            card.pack(fill="x", pady=(0, 20), padx=10)

            sels = core.load_selectors()
            missing = [k for k in core.REQUIRED if k not in sels]
            if not missing or self.wz_calibrated:
                ctk.CTkLabel(card, text="✓ Calibration complete", font=("Segoe UI Variable", 17, "bold"), text_color=TOKEN_OK).pack(pady=(18, 4))
                ctk.CTkLabel(card, text=f"All {len(core.REQUIRED)} required controls mapped successfully.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB).pack(pady=(0, 18))
            else:
                btn_cal = ctk.CTkButton(card, text="Start calibration", height=40, corner_radius=8, fg_color=TOKEN_ACC,
                                        text_color="#FFFFFF", font=("Segoe UI Variable", 13, "bold"), command=self.do_calibrate)
                btn_cal.pack(pady=24, padx=20)

            btn = ctk.CTkButton(self.wz_container, text="Continue", height=40, corner_radius=10, fg_color=TOKEN_ACC,
                                text_color="#FFFFFF", font=("Segoe UI Variable", 14, "bold"), command=lambda: self._set_wz_step(4))
            btn.pack(fill="x", pady=4)
            ctk.CTkButton(self.wz_container, text="Back", height=28, fg_color="transparent", text_color=TOKEN_SUB,
                          font=("Segoe UI Variable", 12), command=lambda: self._set_wz_step(2)).pack()

        # Step 4: All set
        elif s == 4:
            tile = ctk.CTkFrame(self.wz_container, width=76, height=76, corner_radius=19, fg_color=TOKEN_OK)
            tile.pack(pady=(0, 20))
            tile.pack_propagate(False)
            ctk.CTkLabel(tile, text="✓", font=("Segoe UI", 32, "bold"), text_color="#FFFFFF").pack(expand=True)

            ctk.CTkLabel(self.wz_container, text="You’re all set", font=("Segoe UI Variable", 28, "bold"), text_color=TOKEN_TEXT).pack()
            ctk.CTkLabel(self.wz_container, text="Load a script, then press Start batch.", font=("Segoe UI Variable", 14), text_color=TOKEN_SUB).pack(pady=(6, 20))

            card = ctk.CTkFrame(self.wz_container, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
            card.pack(fill="x", pady=(0, 24))

            def finish_row(parent, title, val):
                rf = ctk.CTkFrame(parent, fg_color="transparent")
                rf.pack(fill="x", padx=16, pady=10)
                ctk.CTkLabel(rf, text=title, font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT).pack(side="left")
                ctk.CTkLabel(rf, text=val, font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_OK).pack(side="right")

            finish_row(card, "Sign-in saved", "chrome_profile")
            finish_row(card, "Flow calibrated", f"{len(core.REQUIRED)} of {len(core.REQUIRED)} controls")

            btn = ctk.CTkButton(self.wz_container, text="Go to Run", height=42, corner_radius=10, fg_color=TOKEN_ACC,
                                text_color="#FFFFFF", font=("Segoe UI Variable", 14, "bold"), command=self._finish_wz)
            btn.pack(fill="x", pady=4)

    def _render_setup_complete_screen(self):
        """Renders the Revision 3 'Setup complete' summary screen when Flow Studio is ready."""
        tile = ctk.CTkFrame(self.wz_container, width=76, height=76, corner_radius=19, fg_color=TOKEN_OK)
        tile.pack(pady=(0, 20))
        tile.pack_propagate(False)
        ctk.CTkLabel(tile, text="✓", font=("Segoe UI", 32, "bold"), text_color="#FFFFFF").pack(expand=True)

        ctk.CTkLabel(self.wz_container, text="Setup complete", font=("Segoe UI Variable", 28, "bold"), text_color=TOKEN_TEXT).pack()
        ctk.CTkLabel(self.wz_container, text="Flow Studio is signed in and calibrated. Come back here any time to redo either step.",
                     font=("Segoe UI Variable", 14), text_color=TOKEN_SUB, wraplength=480).pack(pady=(6, 20))

        card = ctk.CTkFrame(self.wz_container, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        card.pack(fill="x", pady=(0, 20))

        def sc_row(parent, title, sub):
            rf = ctk.CTkFrame(parent, fg_color="transparent")
            rf.pack(fill="x", padx=16, pady=12)
            left = ctk.CTkFrame(rf, fg_color="transparent")
            left.pack(side="left")
            ctk.CTkLabel(left, text=title, font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
            ctk.CTkLabel(left, text=sub, font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
            ctk.CTkLabel(rf, text="Found", font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_OK).pack(side="right")

        sc_row(card, "Sign-in saved", "chrome_profile")
        sels_cnt = len(core.REQUIRED) - len([k for k in core.REQUIRED if k not in core.load_selectors()])
        sc_row(card, "Flow calibrated", f"{sels_cnt} of {len(core.REQUIRED)} controls")

        btn_row = ctk.CTkFrame(self.wz_container, fg_color="transparent")
        btn_row.pack(fill="x", pady=6)

        ctk.CTkButton(
            btn_row,
            text="Redo sign-in",
            height=36,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 13, "bold"),
            command=lambda: self._set_wz_step(2),
        ).pack(side="left", expand=True, padx=4)

        ctk.CTkButton(
            btn_row,
            text="Recalibrate",
            height=36,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 13, "bold"),
            command=lambda: self.switch_view("calibrate"),
        ).pack(side="left", expand=True, padx=4)

        ctk.CTkButton(
            self.wz_container,
            text="Run setup wizard again",
            height=30,
            fg_color="transparent",
            text_color=TOKEN_SUB,
            hover_color=TOKEN_FILL,
            font=("Segoe UI Variable", 12),
            command=lambda: self._restart_wizard(),
        ).pack(pady=10)

    def _restart_wizard(self):
        self.needs_setup = True
        self.wz_step = 0
        self._render_wz_step()

    def _set_wz_step(self, step):
        self.needs_setup = True
        self.wz_step = step
        self._render_wz_step()

    def _wz_do_signin(self):
        self.wz_signed = 1
        self.do_login()
        self._render_wz_step()

    def _finish_wz(self):
        self.cfg["setup_complete"] = True
        self.save_settings()
        self.is_fully_setup, self.missing_setup_items, _ = self.check_setup_status()
        self.needs_setup = False
        # Remove Required badge from Setup navigation item
        if "start" in self.nav_btns:
            _, _, badge = self.nav_btns["start"]
            if badge and badge.winfo_exists():
                badge.pack_forget()
        self.switch_view("run")

    # ------------------------------------------------------------- VIEW 2: RUN
    def _build_view_run(self):
        view = ctk.CTkScrollableFrame(self.view_container, fg_color="transparent")

        # Head row
        head = ctk.CTkFrame(view, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 14))

        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="Run", font=("Segoe UI Variable", 28, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        self.run_sub_lbl = ctk.CTkLabel(
            titles,
            text="dynamite-script.md · 8 pairs. Each pair makes an image, then a video.",
            font=("Segoe UI Variable", 13),
            text_color=TOKEN_SUB,
            anchor="w",
        )
        self.run_sub_lbl.pack(fill="x", pady=(2, 0))

        # Top Action Buttons (Stop & Start batch / Resume batch)
        btn_box = ctk.CTkFrame(head, fg_color="transparent")
        btn_box.pack(side="right")

        self.btn_stop = ctk.CTkButton(
            btn_box,
            text="Stop",
            width=70,
            height=34,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_BAD,
            hover_color=TOKEN_BAD,
            font=("Segoe UI Variable", 13, "bold"),
            command=self.do_stop,
            state="disabled",
        )
        self.btn_stop.pack(side="left", padx=4)
        CTkToolTip(self.btn_stop, "Pauses after the current step. Your place is saved.")

        self.btn_restart = ctk.CTkButton(
            btn_box,
            text="Restart from #1",
            width=115,
            height=34,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 13, "bold"),
            command=self.do_restart,
        )
        self.btn_restart.pack(side="left", padx=4)
        CTkToolTip(self.btn_restart, "Starts completely fresh from Pair #1, clearing previous saved progress.")

        self.btn_start = ctk.CTkButton(
            btn_box,
            text="Start batch",
            width=110,
            height=34,
            corner_radius=8,
            fg_color=TOKEN_ACC,
            text_color="#FFFFFF",
            hover_color=TOKEN_ACC_HOVER,
            font=("Segoe UI Variable", 13, "bold"),
            command=self.do_start,
        )
        self.btn_start.pack(side="left", padx=4)
        CTkToolTip(self.btn_start, "Makes an image, then a video, for every pair in the active script.")

        # 1. NOW CARD
        self.now_card = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        self.now_card.pack(fill="x", padx=24, pady=8)

        # 2. ALL PAIRS CARD
        self.all_pairs_card = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        self.all_pairs_card.pack(fill="x", padx=24, pady=8)

        # 3. SAVED PROGRESS CARD
        self.saved_card = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        self.saved_card.pack(fill="x", padx=24, pady=8)

        return view

    # ------------------------------------------------------------- NOW CARD DYNAMICS
    def init_pair_stages(self):
        tot = max(1, len(self.rows))
        self.pair_stages = {}
        for i in range(1, tot + 1):
            self.pair_stages[i] = {"image": "wait", "video": "wait"}

    def render_now_card(self):
        """Renders the prominent Revision 3 'Now Card' matching Flow Studio – Redesign (1).html."""
        for w in self.now_card.winfo_children():
            w.destroy()

        tot = max(1, len(self.rows))
        s_name = self.current_script_path.name if self.current_script_path else "No script loaded"
        if hasattr(self, "run_sub_lbl"):
            self.run_sub_lbl.configure(text=f"{s_name} · {tot} pairs. Each pair makes an image, then a video.")

        container = ctk.CTkFrame(self.now_card, fg_color="transparent")
        container.pack(fill="x", padx=20, pady=20)

        # State 1: Not started yet
        if not self.batch_started:
            if self.pending_scripts == 0 and not self.is_running:
                pill = ctk.CTkFrame(container, fg_color="transparent")
                pill.pack(anchor="w")
                ctk.CTkLabel(pill, text="●", font=("Segoe UI", 10), text_color=TOKEN_OK).pack(side="left", padx=(0, 6))
                ctk.CTkLabel(pill, text="All scripts complete", font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_OK).pack(side="left")

                ctk.CTkLabel(container, text="All scripts completed!", font=("Segoe UI Variable", 32, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x", pady=(6, 2))
                ctk.CTkLabel(container, text="All markdown scripts have been processed and moved to completed/. Add a new markdown script to scripts/ to run another batch.",
                             font=("Segoe UI Variable", 13), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
                self.btn_start.configure(text="Start batch")
                return

            pill = ctk.CTkFrame(container, fg_color="transparent")
            pill.pack(anchor="w")
            ctk.CTkLabel(pill, text="●", font=("Segoe UI", 10), text_color=TOKEN_SUB).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(pill, text="Ready", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB).pack(side="left")

            ctk.CTkLabel(container, text="Ready to run", font=("Segoe UI Variable", 32, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x", pady=(6, 2))
            ctk.CTkLabel(container, text="Press Start batch. You will see each pair’s image and video progress here.",
                         font=("Segoe UI Variable", 13), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
            self.btn_start.configure(text="Start batch")
            return

        # State 2: Active / Running / Paused / Needs Attention / Complete
        dn = self.video_generated
        sk = self.skipped_count
        fin = (dn + sk >= tot)
        is_clean_complete = (dn >= tot and sk == 0)
        has_issues = (sk > 0)
        is_err = self.current_error is not None

        if is_clean_complete:
            status_text = "Complete"
            dot_color = TOKEN_OK
        elif has_issues and fin:
            status_text = f"Finished with issues ({sk} failed)"
            dot_color = TOKEN_BAD
        elif has_issues:
            status_text = f"Has failed pairs ({sk} issues)"
            dot_color = TOKEN_BAD
        elif is_err:
            status_text = "Needs your attention"
            dot_color = TOKEN_BAD
        elif self.is_running:
            status_text = "Running"
            dot_color = TOKEN_OK
        else:
            status_text = "Paused"
            dot_color = ("#F59E0B", "#FBBF24")

        # Top status pill + script filename row
        top_row = ctk.CTkFrame(container, fg_color="transparent")
        top_row.pack(fill="x")

        pill_box = ctk.CTkFrame(top_row, fg_color="transparent")
        pill_box.pack(side="left")
        ctk.CTkLabel(pill_box, text="●", font=("Segoe UI", 11), text_color=dot_color).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(pill_box, text=status_text, font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_TEXT).pack(side="left")

        ctk.CTkLabel(top_row, text=s_name, font=("Segoe UI Variable", 12), text_color=TOKEN_SUB).pack(side="right")

        # Large Metric Count Headline
        h_text = f"{dn} of {tot} videos"
        if sk > 0:
            h_text += f" · {sk} failed/skipped"
        ctk.CTkLabel(container, text=h_text, font=("Segoe UI Variable", 32, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x", pady=(6, 8))

        # Progress Track Bar
        prog_val = min(1.0, (dn + sk) / max(1, tot))
        pbar = ctk.CTkProgressBar(container, height=6, corner_radius=3, progress_color=TOKEN_ACC, fg_color=TOKEN_FILL)
        pbar.set(prog_val)
        pbar.pack(fill="x", pady=(0, 16))

        # If batch is not complete: Render active pair row
        cur_pair = min(tot, max(1, self.current_pair_idx))
        cur_row = self.rows[cur_pair - 1] if cur_pair <= len(self.rows) else None
        pair_title = cur_row.get_title() if cur_row else f"Pair {cur_pair}"
        img_p, vid_p = cur_row.get() if cur_row else ("", "")

        p_stages = self.pair_stages.get(cur_pair, {"image": "wait", "video": "wait"})

        if not fin:
            nowrow = ctk.CTkFrame(container, fg_color="transparent")
            nowrow.pack(fill="x", pady=4)

            # 9:16 Thumbnail preview card
            thumb_col = ("#F6C177", "#B5651D") if p_stages.get("image") in ["ok", "work"] or str(p_stages.get("image", "")).startswith("work:") else TOKEN_FILL
            th = ctk.CTkFrame(nowrow, width=96, height=140, corner_radius=12, fg_color=thumb_col)
            th.pack(side="left", padx=(0, 16))
            th.pack_propagate(False)
            th_icon = "🎬" if p_stages.get("video") == "ok" else ("🖼" if p_stages.get("image") == "ok" else "⋯")
            ctk.CTkLabel(th, text=th_icon, font=("Segoe UI", 26), text_color=("#3A2A1A", "#FFFFFF")).pack(expand=True)

            # Details
            details = ctk.CTkFrame(nowrow, fg_color="transparent")
            details.pack(side="left", fill="both", expand=True)

            ctk.CTkLabel(details, text=f"Pair {cur_pair} of {tot} · {pair_title}", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
            prompt_snip = img_p if len(img_p) < 140 else img_p[:136] + "…"
            ctk.CTkLabel(details, text=prompt_snip or "No image prompt entered.", font=("Segoe UI Variable", 13), text_color=TOKEN_TEXT, anchor="w", wraplength=480, justify="left").pack(fill="x", pady=(2, 10))

            # Two-stage pipeline tracker (1 · Image  |  2 · Video)
            pipe = ctk.CTkFrame(details, fg_color="transparent")
            pipe.pack(fill="x")
            pipe.columnconfigure(0, weight=1)
            pipe.columnconfigure(1, weight=1)

            def make_stage_box(parent, col_idx, stage_num, stage_name, state_code):
                # state_code: wait | work | work:XX% | ok | err | skip
                status_labels = {
                    "wait": ("Waiting", TOKEN_SUB, TOKEN_FILL, 0),
                    "work": ("◐ In progress", TOKEN_ACC, TOKEN_FILL, 2),
                    "ok": ("✓ Done", TOKEN_OK, TOKEN_FILL, 0),
                    "err": ("✕ Rejected", TOKEN_BAD, ("#FEE2E2", "#450A0A"), 2),
                    "skip": ("Skipped", TOKEN_SUB, TOKEN_FILL, 0),
                }
                if isinstance(state_code, str) and state_code.startswith("work:"):
                    pct_val = state_code.split(":", 1)[1]
                    lbl_t, col_t, bg_t, b_w = (f"◐ Generating ({pct_val})", TOKEN_ACC, TOKEN_FILL, 2)
                else:
                    lbl_t, col_t, bg_t, b_w = status_labels.get(state_code, ("Waiting", TOKEN_SUB, TOKEN_FILL, 0))

                kwargs = {"fg_color": bg_t, "corner_radius": 10}
                if b_w > 0:
                    kwargs["border_color"] = col_t
                    kwargs["border_width"] = b_w
                stg_f = ctk.CTkFrame(parent, **kwargs)
                stg_f.grid(row=0, column=col_idx, sticky="nsew", padx=4)

                ctk.CTkLabel(stg_f, text=f"{stage_num} · {stage_name}", font=("Segoe UI Variable", 11), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=12, pady=(8, 2))
                ctk.CTkLabel(stg_f, text=lbl_t, font=("Segoe UI Variable", 13, "bold"), text_color=col_t, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

            make_stage_box(pipe, 0, "1", "Image", p_stages.get("image", "wait"))
            make_stage_box(pipe, 1, "2", "Video", p_stages.get("video", "wait"))

        # Policy Violation / Error Banner
        if is_err:
            err_data = self.current_error
            banner = ctk.CTkFrame(container, fg_color=("#FFF1F2", "#3B181A"), border_color=("#FECDD3", "#991B1B"), border_width=1, corner_radius=12)
            banner.pack(fill="x", pady=(16, 0))

            b_in = ctk.CTkFrame(banner, fg_color="transparent")
            b_in.pack(fill="x", padx=16, pady=14)

            err_pair = err_data.get("pair", cur_pair)
            err_stage = err_data.get("stage", "image")
            ctk.CTkLabel(b_in, text=f"Policy violation on pair {err_pair} ({err_stage})", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_BAD, anchor="w").pack(fill="x")
            ctk.CTkLabel(b_in, text="Flow declined this prompt. Rewording the prompt usually fixes it. Your progress is saved, so nothing is lost.",
                         font=("Segoe UI Variable", 12), text_color=TOKEN_TEXT, anchor="w").pack(fill="x", pady=(4, 12))

            act_row = ctk.CTkFrame(b_in, fg_color="transparent")
            act_row.pack(fill="x")

            ctk.CTkButton(
                act_row,
                text="Retry",
                height=30,
                width=76,
                corner_radius=8,
                fg_color=TOKEN_ACC,
                text_color="#FFFFFF",
                font=("Segoe UI Variable", 12, "bold"),
                command=self.on_banner_retry,
            ).pack(side="left", padx=(0, 8))

            ctk.CTkButton(
                act_row,
                text="Edit prompt",
                height=30,
                width=90,
                corner_radius=8,
                fg_color=TOKEN_FILL,
                text_color=TOKEN_TEXT,
                hover_color=TOKEN_LINE,
                font=("Segoe UI Variable", 12, "bold"),
                command=lambda: self.open_inspect_error_modal(),
            ).pack(side="left", padx=4)

            ctk.CTkButton(
                act_row,
                text="Skip pair",
                height=30,
                width=76,
                corner_radius=8,
                fg_color=TOKEN_FILL,
                text_color=TOKEN_TEXT,
                hover_color=TOKEN_LINE,
                font=("Segoe UI Variable", 12, "bold"),
                command=self.on_banner_skip,
            ).pack(side="left", padx=4)

        # Prominent Resume and Start Fresh buttons directly inside Now Card
        if not self.is_running and (self.batch_started or self.current_pair_idx > 1 or has_issues or (fin and not is_clean_complete)):
            res_row = ctk.CTkFrame(container, fg_color="transparent")
            res_row.pack(fill="x", pady=(14, 0))

            if not is_clean_complete and not fin:
                ctk.CTkButton(
                    res_row,
                    text="▶ Resume batch",
                    height=36,
                    corner_radius=8,
                    fg_color=TOKEN_ACC,
                    text_color="#FFFFFF",
                    font=("Segoe UI Variable", 13, "bold"),
                    command=lambda: self.do_start(resume=True),
                ).pack(side="left", padx=(0, 8))

            ctk.CTkButton(
                res_row,
                text="↺ Start fresh (Pair #1)",
                height=36,
                corner_radius=8,
                fg_color=TOKEN_FILL,
                text_color=TOKEN_TEXT,
                hover_color=TOKEN_LINE,
                font=("Segoe UI Variable", 12, "bold"),
                command=self.do_restart,
            ).pack(side="left")

        btn_txt = "▶ Resume batch" if (self.batch_started and not self.is_running and not is_clean_complete) else "Start batch"
        self.btn_start.configure(state="normal" if not self.is_running else "disabled", text=btn_txt)

    def on_banner_retry(self):
        self.current_error = None
        if hasattr(self.ui, "user_decision"):
            self.ui.user_decision.put("retry")
        else:
            self.do_start(resume=True)
        self.render_now_card()

    def on_banner_skip(self):
        self.current_error = None
        self.skipped_count += 1
        if hasattr(self.ui, "user_decision"):
            self.ui.user_decision.put("skip")
        else:
            self.current_pair_idx += 1
            self.do_start(resume=True)
        self.render_now_card()

    # ------------------------------------------------------------- ALL PAIRS CARD
    def render_all_pairs_card(self):
        for w in self.all_pairs_card.winfo_children():
            w.destroy()

        ctk.CTkLabel(self.all_pairs_card, text="All pairs", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=18, pady=(12, 6))

        for i, row in enumerate(self.rows, 1):
            st = self.pair_stages.get(i, {"image": "wait", "video": "wait"})

            # Chip text and style
            if st.get("image") == "err" or st.get("video") == "err":
                chip_txt = "Image rejected" if st.get("image") == "err" else "Video rejected"
                chip_fg = TOKEN_BAD
                chip_bg = ("#FEE2E2", "#450A0A")
            elif st.get("image") == "skip" or st.get("video") == "skip":
                chip_txt = "Skipped"
                chip_fg = TOKEN_SUB
                chip_bg = TOKEN_FILL
            elif st.get("video") == "ok":
                chip_txt = "Done"
                chip_fg = TOKEN_OK
                chip_bg = ("#DCFCE7", "#14532D")
            elif st.get("video") == "work" or str(st.get("video", "")).startswith("work:"):
                vid_st = str(st.get("video", ""))
                chip_txt = f"Video ({vid_st.split(':', 1)[1]})" if vid_st.startswith("work:") else "Making video"
                chip_fg = TOKEN_ACC
                chip_bg = ("#E0F2FE", "#0C4A6E")
            elif st.get("image") == "work" or str(st.get("image", "")).startswith("work:"):
                img_st = str(st.get("image", ""))
                chip_txt = f"Image ({img_st.split(':', 1)[1]})" if img_st.startswith("work:") else "Making image"
                chip_fg = TOKEN_ACC
                chip_bg = ("#E0F2FE", "#0C4A6E")
            else:
                chip_txt = "Waiting"
                chip_fg = TOKEN_SUB
                chip_bg = TOKEN_FILL

            pr = ctk.CTkFrame(self.all_pairs_card, fg_color="transparent")
            pr.pack(fill="x", padx=18, pady=4)

            ctk.CTkLabel(pr, text=str(i), width=24, font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_SUB, anchor="w").pack(side="left")
            title_text = row.get_title()
            ctk.CTkLabel(pr, text=title_text, font=("Segoe UI Variable", 13), text_color=TOKEN_TEXT, anchor="w").pack(side="left", fill="x", expand=True, padx=8)

            chip = ctk.CTkLabel(
                pr,
                text=chip_txt,
                font=("Segoe UI Variable", 11, "bold"),
                fg_color=chip_bg,
                text_color=chip_fg,
                corner_radius=10,
                padx=10,
                pady=2,
            )
            chip.pack(side="right")

        ctk.CTkFrame(self.all_pairs_card, height=8, fg_color="transparent").pack()

    # ------------------------------------------------------------- SAVED PROGRESS CARD
    def render_saved_progress_card(self):
        for w in self.saved_card.winfo_children():
            w.destroy()

        ctk.CTkLabel(self.saved_card, text="Saved progress", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=18, pady=(12, 6))

        s_name = self.current_script_path.name if self.current_script_path else "None"
        tot = len(self.rows)
        dn = self.video_generated
        sk = self.skipped_count

        is_clean_complete = (dn >= tot and sk == 0)
        if not self.batch_started and not sk and not dn:
            sub = "Not started"
            chip_label = "Ready"
            chip_col = TOKEN_SUB
            chip_bg = TOKEN_FILL
            show_resume = False
        elif is_clean_complete:
            sub = f"{dn} of {tot} done · complete"
            chip_label = "Complete"
            chip_col = TOKEN_OK
            chip_bg = ("#DCFCE7", "#14532D")
            show_resume = False
        elif sk > 0:
            sub = f"{dn} of {tot} done · {sk} failed/skipped"
            chip_label = f"{sk} issue{'s' if sk > 1 else ''}"
            chip_col = TOKEN_BAD
            chip_bg = ("#FEE2E2", "#450A0A")
            show_resume = True
        elif self.current_error:
            sub = f"{dn} of {tot} done · stopped on pair {self.current_pair_idx}: error"
            chip_label = "Needs attention"
            chip_col = TOKEN_BAD
            chip_bg = ("#FEE2E2", "#450A0A")
            show_resume = True
        elif self.is_running:
            sub = f"{dn} of {tot} done · running"
            chip_label = "Active"
            chip_col = TOKEN_ACC
            chip_bg = ("#E0F2FE", "#0C4A6E")
            show_resume = False
        else:
            sub = f"{dn} of {tot} done · paused"
            chip_label = "Paused"
            chip_col = ("#F59E0B", "#FBBF24")
            chip_bg = ("#FEF3C7", "#78350F")
            show_resume = True

        # Active Script Item
        it = ctk.CTkFrame(self.saved_card, fg_color="transparent")
        it.pack(fill="x", padx=18, pady=8)

        left = ctk.CTkFrame(it, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text=s_name, font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(left, text=sub, font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")

        if show_resume:
            btn_box = ctk.CTkFrame(it, fg_color="transparent")
            btn_box.pack(side="right")
            if self.current_error:
                ctk.CTkButton(
                    btn_box,
                    text="Inspect Error",
                    height=28,
                    width=90,
                    corner_radius=8,
                    fg_color=TOKEN_FILL,
                    text_color=TOKEN_BAD,
                    hover_color=TOKEN_LINE,
                    font=("Segoe UI Variable", 12, "bold"),
                    command=lambda: self.open_inspect_error_modal(),
                ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(
                btn_box,
                text="Restart from #1",
                height=28,
                width=100,
                corner_radius=8,
                fg_color=TOKEN_FILL,
                text_color=TOKEN_TEXT,
                hover_color=TOKEN_LINE,
                font=("Segoe UI Variable", 12, "bold"),
                command=self.do_restart,
            ).pack(side="left", padx=(0, 6))
            if not (dn + sk >= tot):
                b_res = ctk.CTkButton(
                    btn_box,
                    text="Resume",
                    height=28,
                    width=72,
                    corner_radius=8,
                    fg_color=TOKEN_ACC,
                    text_color="#FFFFFF",
                    hover_color=TOKEN_ACC_HOVER,
                    font=("Segoe UI Variable", 12, "bold"),
                    command=lambda: self.do_start(resume=True),
                )
                b_res.pack(side="left")
        else:
            chip = ctk.CTkLabel(
                it,
                text=chip_label,
                font=("Segoe UI Variable", 11, "bold"),
                fg_color=chip_bg,
                text_color=chip_col,
                corner_radius=10,
                padx=10,
                pady=2,
            )
            chip.pack(side="right")

        # Historical / completed states from disk
        try:
            states_dir = core.LOGS_DIR / "script_states"
            if states_dir.exists():
                for sf in sorted(states_dir.glob("*_state.json")):
                    try:
                        data = json.loads(sf.read_text(encoding="utf-8"))
                        hist_name = data.get("script_name", sf.stem)
                        if hist_name == s_name:
                            continue  # already shown above
                        hist_comp = len(data.get("completed_pairs", []))
                        hist_tot = data.get("total_pairs", 8)
                        hist_fails = data.get("failed_pairs", [])
                        hist_sub = f"{hist_comp} of {hist_tot} done"
                        if hist_fails:
                            hist_sub += f" · {len(hist_fails)} issues"
                            h_chip_txt = f"{len(hist_fails)} issue{'s' if len(hist_fails) > 1 else ''}"
                            h_chip_col = TOKEN_BAD
                            h_chip_bg = ("#FEE2E2", "#450A0A")
                        else:
                            hist_sub += " · moved to completed"
                            h_chip_txt = "Complete"
                            h_chip_col = TOKEN_OK
                            h_chip_bg = ("#DCFCE7", "#14532D")

                        h_it = ctk.CTkFrame(self.saved_card, fg_color="transparent")
                        h_it.pack(fill="x", padx=18, pady=6)
                        h_left = ctk.CTkFrame(h_it, fg_color="transparent")
                        h_left.pack(side="left", fill="x", expand=True)
                        ctk.CTkLabel(h_left, text=hist_name, font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
                        ctk.CTkLabel(h_left, text=hist_sub, font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")

                        if hist_fails:
                            ctk.CTkButton(
                                h_it,
                                text="Inspect",
                                height=26,
                                width=60,
                                corner_radius=6,
                                fg_color=TOKEN_FILL,
                                text_color=TOKEN_BAD,
                                hover_color=TOKEN_LINE,
                                font=("Segoe UI Variable", 11, "bold"),
                                command=lambda f_data=hist_fails[0], sn=hist_name: self.open_inspect_error_modal({**f_data, "script_name": sn}),
                            ).pack(side="right", padx=(6, 0))

                        ctk.CTkLabel(
                            h_it,
                            text=h_chip_txt,
                            font=("Segoe UI Variable", 11, "bold"),
                            fg_color=h_chip_bg,
                            text_color=h_chip_col,
                            corner_radius=10,
                            padx=10,
                            pady=2,
                        ).pack(side="right")
                    except Exception:
                        pass
        except Exception:
            pass

        ctk.CTkFrame(self.saved_card, height=8, fg_color="transparent").pack()

    # ------------------------------------------------------------- VIEW: PROBLEMS & ERRORS
    def _build_view_problems(self):
        view = ctk.CTkFrame(self.view_container, fg_color="transparent")

        # Head row
        head = ctk.CTkFrame(view, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 14))

        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="Problems & Errors", font=("Segoe UI Variable", 28, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(titles, text="Review scripts with failed prompt pairs, safety flags, or timeouts, and replay or edit them.",
                     font=("Segoe UI Variable", 13), text_color=TOKEN_SUB, anchor="w").pack(fill="x", pady=(2, 0))

        # Actions
        btn_box = ctk.CTkFrame(head, fg_color="transparent")
        btn_box.pack(side="right")

        b_refresh = ctk.CTkButton(
            btn_box,
            text="🔄 Refresh",
            width=88,
            height=30,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 12, "bold"),
            command=self.render_problems_view,
        )
        b_refresh.pack(side="left", padx=4)

        b_clear = ctk.CTkButton(
            btn_box,
            text="Clear Resolved",
            width=104,
            height=30,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 12, "bold"),
            command=self.clear_resolved_problems,
        )
        b_clear.pack(side="left", padx=4)

        # Scrollable container for problems cards
        self.problems_scroll = ctk.CTkScrollableFrame(
            view,
            fg_color="transparent",
            corner_radius=0,
        )
        self.problems_scroll.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        return view

    def get_all_problems(self):
        """Scans active state and logs/script_states/*.json to gather all failed prompt pairs and issues."""
        problems = {}

        # 1. From logs/script_states/*.json
        states_dir = core.LOGS_DIR / "script_states"
        if states_dir.exists():
            for f in sorted(states_dir.glob("*_state.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    failed = data.get("failed_pairs", [])
                    if failed or data.get("status") == "completed_with_errors":
                        s_name = data.get("script_name", f.stem.replace("_state", ".md"))
                        s_file = data.get("script_file", "")
                        problems[f.stem] = {
                            "stem": f.stem.replace("_state", ""),
                            "script_name": s_name,
                            "script_file": s_file,
                            "status": data.get("status", "completed_with_errors"),
                            "timestamp": data.get("timestamp", ""),
                            "failed_pairs": list(failed),
                        }
                except Exception:
                    pass

        # 2. From logs/policy_violations.json
        if core.POLICY_LOGS_FILE.exists():
            try:
                viols = json.loads(core.POLICY_LOGS_FILE.read_text(encoding="utf-8"))
                for v in viols:
                    s_name = v.get("script_name", "Unknown script")
                    stem = Path(s_name).stem
                    if stem not in problems:
                        problems[stem] = {
                            "stem": stem,
                            "script_name": s_name,
                            "script_file": str(self.scripts_dir / s_name),
                            "status": "flagged",
                            "timestamp": v.get("timestamp", ""),
                            "failed_pairs": [],
                        }
                    p_idx = v.get("pair_index")
                    exists = any(fp.get("pair") == p_idx and fp.get("stage") == v.get("stage") for fp in problems[stem]["failed_pairs"])
                    if not exists:
                        problems[stem]["failed_pairs"].append({
                            "pair": p_idx,
                            "stage": v.get("stage", "image"),
                            "reason": v.get("reason", "Policy violation"),
                            "image_prompt": v.get("image_prompt", ""),
                            "video_prompt": v.get("video_prompt", ""),
                        })
            except Exception:
                pass

        # 3. From active in-memory error
        if self.current_error:
            s_name = self.active_script_name if self.active_script_name != "None" else "Active Run"
            stem = Path(s_name).stem
            if stem not in problems:
                problems[stem] = {
                    "stem": stem,
                    "script_name": s_name,
                    "script_file": str(self.current_script_path) if self.current_script_path else "",
                    "status": "active_error",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "failed_pairs": [],
                }
            p_idx = self.current_error.get("pair", self.current_pair_idx)
            exists = any(fp.get("pair") == p_idx for fp in problems[stem]["failed_pairs"])
            if not exists:
                problems[stem]["failed_pairs"].append({
                    "pair": p_idx,
                    "stage": self.current_error.get("stage", "image"),
                    "reason": self.current_error.get("message", "Error"),
                    "image_prompt": self.current_error.get("image_prompt", ""),
                    "video_prompt": self.current_error.get("video_prompt", ""),
                })

        return list(problems.values())

    def update_problems_badge(self):
        """Updates the Problems nav item badge in the sidebar with active issue count."""
        if "problems" not in self.nav_btns:
            return
        btn_f, btn, badge = self.nav_btns["problems"]
        probs = self.get_all_problems()
        total_issues = sum(len(p.get("failed_pairs", [])) for p in probs)

        if total_issues > 0:
            if not badge:
                badge = ctk.CTkLabel(
                    btn_f,
                    text=str(total_issues),
                    font=("Segoe UI Variable", 10, "bold"),
                    fg_color=TOKEN_BAD,
                    text_color="#FFFFFF",
                    corner_radius=6,
                    padx=6,
                    pady=1,
                )
                badge.pack(side="right", padx=6)
                self.nav_btns["problems"] = (btn_f, btn, badge)
            else:
                badge.configure(text=str(total_issues), fg_color=TOKEN_BAD)
        else:
            if badge and badge.winfo_exists():
                badge.configure(text="", fg_color="transparent")

    def render_problems_view(self):
        """Renders the Problems & Errors view with all failed scripts and prompt pairs."""
        if not hasattr(self, "problems_scroll"):
            return
        for w in self.problems_scroll.winfo_children():
            w.destroy()

        problems = self.get_all_problems()
        self.update_problems_badge()

        if not problems:
            # Clean Empty State
            empty_card = ctk.CTkFrame(
                self.problems_scroll,
                fg_color=TOKEN_CARD,
                border_color=TOKEN_LINE,
                border_width=1,
                corner_radius=14,
            )
            empty_card.pack(fill="x", pady=10)

            c_box = ctk.CTkFrame(empty_card, fg_color="transparent")
            c_box.pack(padx=24, pady=36, fill="both")

            ctk.CTkLabel(
                c_box,
                text="✓",
                font=("Segoe UI Variable", 36, "bold"),
                text_color=TOKEN_OK,
            ).pack(pady=(0, 6))

            ctk.CTkLabel(
                c_box,
                text="No Problems Detected",
                font=("Segoe UI Variable", 18, "bold"),
                text_color=TOKEN_TEXT,
            ).pack(pady=(0, 4))

            ctk.CTkLabel(
                c_box,
                text="All scripts ran cleanly without policy violations or timeouts, or all issues have been resolved.",
                font=("Segoe UI Variable", 13),
                text_color=TOKEN_SUB,
            ).pack()
            return

        # Render each script that has problems
        for prob in problems:
            s_name = prob.get("script_name", "Unknown script")
            s_file = prob.get("script_file", "")
            failed_pairs = prob.get("failed_pairs", [])
            ts = prob.get("timestamp", "")
            f_count = len(failed_pairs)

            card = ctk.CTkFrame(
                self.problems_scroll,
                fg_color=TOKEN_CARD,
                border_color=TOKEN_LINE,
                border_width=1,
                corner_radius=14,
            )
            card.pack(fill="x", pady=8)

            # Card Header
            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.pack(fill="x", padx=18, pady=(14, 10))

            hdr_left = ctk.CTkFrame(hdr, fg_color="transparent")
            hdr_left.pack(side="left")

            ctk.CTkLabel(
                hdr_left,
                text=s_name,
                font=("Segoe UI Variable", 15, "bold"),
                text_color=TOKEN_TEXT,
            ).pack(side="left", padx=(0, 8))

            ctk.CTkLabel(
                hdr_left,
                text=f"{f_count} failed pair{'s' if f_count != 1 else ''}",
                font=("Segoe UI Variable", 11, "bold"),
                fg_color=TOKEN_BAD,
                text_color="#FFFFFF",
                corner_radius=6,
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 8))

            if ts:
                ctk.CTkLabel(
                    hdr_left,
                    text=f"Logged: {ts[:19].replace('T', ' ')}",
                    font=("Segoe UI Variable", 11),
                    text_color=TOKEN_SUB,
                ).pack(side="left")

            hdr_right = ctk.CTkFrame(hdr, fg_color="transparent")
            hdr_right.pack(side="right")

            target_p = Path(s_file) if s_file else (self.scripts_dir / s_name)

            ctk.CTkButton(
                hdr_right,
                text="📂 Edit in Prompts",
                width=110,
                height=28,
                corner_radius=6,
                fg_color=TOKEN_FILL,
                text_color=TOKEN_TEXT,
                hover_color=TOKEN_LINE,
                font=("Segoe UI Variable", 11, "bold"),
                command=lambda p=target_p: self.load_problem_script_into_editor(p),
            ).pack(side="left", padx=3)

            ctk.CTkButton(
                hdr_right,
                text="▶ Replay Script",
                width=100,
                height=28,
                corner_radius=6,
                fg_color=TOKEN_ACC,
                text_color="#FFFFFF",
                hover_color=TOKEN_ACC_HOVER,
                font=("Segoe UI Variable", 11, "bold"),
                command=lambda p=target_p, pairs=failed_pairs: self.replay_problem_script(p, pairs),
            ).pack(side="left", padx=3)

            ctk.CTkButton(
                hdr_right,
                text="⏭ Skip Script",
                width=90,
                height=28,
                corner_radius=6,
                fg_color=TOKEN_FILL,
                text_color=TOKEN_SUB,
                hover_color=TOKEN_LINE,
                font=("Segoe UI Variable", 11, "bold"),
                command=lambda p=target_p, s=s_name: self.skip_problem_script(p, s),
            ).pack(side="left", padx=3)

            ctk.CTkButton(
                hdr_right,
                text="✕ Clear",
                width=72,
                height=28,
                corner_radius=6,
                fg_color=TOKEN_FILL,
                text_color=TOKEN_BAD,
                hover_color=TOKEN_LINE,
                font=("Segoe UI Variable", 11, "bold"),
                command=lambda st=prob.get("stem", Path(s_name).stem), s=s_name: self.dismiss_problem_script(st, s),
            ).pack(side="left", padx=3)

            # Divider
            ctk.CTkFrame(card, height=1, fg_color=TOKEN_LINE).pack(fill="x", padx=16, pady=4)

            # List of failed pairs
            for fp in failed_pairs:
                p_num = fp.get("pair", 1)
                stage = fp.get("stage", "image")
                reason = fp.get("reason", "Failure")
                img_pr = fp.get("image_prompt", "")
                vid_pr = fp.get("video_prompt", "")

                p_row = ctk.CTkFrame(card, fg_color=TOKEN_FILL, corner_radius=10)
                p_row.pack(fill="x", padx=16, pady=6)

                p_top = ctk.CTkFrame(p_row, fg_color="transparent")
                p_top.pack(fill="x", padx=12, pady=(10, 4))

                top_l = ctk.CTkFrame(p_top, fg_color="transparent")
                top_l.pack(side="left")

                ctk.CTkLabel(
                    top_l,
                    text=f"Pair #{p_num}",
                    font=("Segoe UI Variable", 13, "bold"),
                    text_color=TOKEN_TEXT,
                ).pack(side="left", padx=(0, 8))

                stg_color = TOKEN_WARN if stage == "image" else TOKEN_BAD
                ctk.CTkLabel(
                    top_l,
                    text=f"{stage.upper()} STAGE",
                    font=("Segoe UI Variable", 10, "bold"),
                    fg_color=stg_color,
                    text_color="#FFFFFF",
                    corner_radius=6,
                    padx=6,
                    pady=1,
                ).pack(side="left", padx=(0, 8))

                top_r = ctk.CTkFrame(p_top, fg_color="transparent")
                top_r.pack(side="right")

                pair_err_data = {
                    "pair": p_num,
                    "stage": stage,
                    "reason": reason,
                    "message": reason,
                    "image_prompt": img_pr,
                    "video_prompt": vid_pr,
                    "script_name": s_name,
                    "script_file": str(target_p),
                }

                ctk.CTkButton(
                    top_r,
                    text="🔍 Inspect & Edit",
                    width=100,
                    height=26,
                    corner_radius=6,
                    fg_color=TOKEN_CARD,
                    text_color=TOKEN_ACC,
                    hover_color=TOKEN_LINE,
                    font=("Segoe UI Variable", 11, "bold"),
                    command=lambda ed=pair_err_data: self.open_inspect_error_modal(ed),
                ).pack(side="left", padx=3)

                ctk.CTkButton(
                    top_r,
                    text="▶ Replay this Pair",
                    width=110,
                    height=26,
                    corner_radius=6,
                    fg_color=TOKEN_ACC,
                    text_color="#FFFFFF",
                    hover_color=TOKEN_ACC_HOVER,
                    font=("Segoe UI Variable", 11, "bold"),
                    command=lambda p=target_p, idx=p_num: self.replay_problem_pair(p, idx),
                ).pack(side="left", padx=3)

                # Reason notice
                clean_reason = reason.replace("\n", " ").strip()
                ctk.CTkLabel(
                    p_row,
                    text=f"Notice: {clean_reason[:120]}{'…' if len(clean_reason) > 120 else ''}",
                    font=("Segoe UI Variable", 12),
                    text_color=TOKEN_BAD,
                    anchor="w",
                ).pack(fill="x", padx=12, pady=(0, 4))

                # Prompts summary
                if img_pr or vid_pr:
                    pr_box = ctk.CTkFrame(p_row, fg_color="transparent")
                    pr_box.pack(fill="x", padx=12, pady=(2, 10))
                    if img_pr:
                        c_img = img_pr.splitlines()[0][:70]
                        ctk.CTkLabel(pr_box, text=f"Image: {c_img}…", font=("Segoe UI Variable", 11), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
                    if vid_pr:
                        c_vid = vid_pr.splitlines()[0][:70]
                        ctk.CTkLabel(pr_box, text=f"Video: {c_vid}…", font=("Segoe UI Variable", 11), text_color=TOKEN_SUB, anchor="w").pack(fill="x")

    def load_problem_script_into_editor(self, script_path):
        """Loads the problem script into the Scripts & Prompts editor."""
        p = Path(script_path)
        if p.exists():
            self.load_script_file(p, reset_state=False)
            self.switch_view("prompts")
        else:
            messagebox.showinfo("Script not found", f"Script file '{p.name}' is not in scripts/ folder.")

    def replay_problem_script(self, script_path, failed_pairs):
        """Loads the problem script, sets standing pair index to the first failed pair, and resumes batch."""
        p = Path(script_path)
        if not p.exists() and (self.scripts_dir / "completed" / p.name).exists():
            dest = self.scripts_dir / p.name
            try:
                shutil.move(str(self.scripts_dir / "completed" / p.name), str(dest))
                p = dest
            except Exception:
                pass
        if not p.exists():
            messagebox.showinfo("Script not found", f"Script file '{p.name}' is not in scripts/ folder.")
            return
        self.load_script_file(p, reset_state=False)
        first_fail = failed_pairs[0].get("pair", 1) if failed_pairs else 1
        self.current_pair_idx = first_fail
        self.current_error = None
        self.batch_started = True
        self.init_pair_stages()
        self.switch_view("run")
        self.render_now_card()
        self.render_all_pairs_card()
        self.do_start(resume=True)

    def replay_problem_pair(self, script_path, pair_num):
        """Replays an individual failed pair from the Problems view."""
        p = Path(script_path)
        if not p.exists() and (self.scripts_dir / "completed" / p.name).exists():
            dest = self.scripts_dir / p.name
            try:
                shutil.move(str(self.scripts_dir / "completed" / p.name), str(dest))
                p = dest
            except Exception:
                pass
        if p.exists() and (not self.current_script_path or self.current_script_path.resolve() != p.resolve()):
            self.load_script_file(p, reset_state=False)
        self.current_pair_idx = pair_num
        self.current_error = None
        self.batch_started = True
        if pair_num in self.pair_stages:
            self.pair_stages[pair_num] = {"image": "wait", "video": "wait"}
        self.switch_view("run")
        self.render_now_card()
        self.render_all_pairs_card()
        self.do_start(resume=True)

    def dismiss_problem_script(self, script_stem, script_name):
        """Clears all logged errors and failure state for a specific script."""
        try:
            stems_to_try = {script_stem, script_stem.replace("-", "_"), script_stem.replace("_", "-"), Path(script_name).stem}
            for st in stems_to_try:
                st_file = core.SCRIPT_STATES_DIR / f"{st}_state.json"
                if st_file.exists():
                    try:
                        data = json.loads(st_file.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            data["failed_pairs"] = []
                            data["policy_violations"] = []
                            if data.get("status") == "completed_with_errors":
                                data["status"] = "completed"
                            st_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass

                rep_file = core.SCRIPT_STATES_DIR / f"{st}_failures.txt"
                if rep_file.exists():
                    try:
                        rep_file.unlink()
                    except Exception:
                        pass

            if core.POLICY_LOGS_FILE.exists():
                try:
                    viols = json.loads(core.POLICY_LOGS_FILE.read_text(encoding="utf-8"))
                    filtered = [v for v in viols if v.get("script_name") != script_name and Path(v.get("script_name", "")).stem != script_stem]
                    core.POLICY_LOGS_FILE.write_text(json.dumps(filtered, indent=2), encoding="utf-8")
                except Exception:
                    pass

            if self.active_script_name == script_name or (self.current_script_path and self.current_script_path.stem == script_stem):
                self.current_error = None
                self.skipped_count = 0
                for i, stg in self.pair_stages.items():
                    if stg.get("image") == "err":
                        stg["image"] = "wait"
                    if stg.get("video") == "err":
                        stg["video"] = "wait"
                b_state = core.load_batch_state()
                if b_state and (b_state.get("script_name") == script_name or Path(b_state.get("script_file", "")).stem == script_stem):
                    b_state["failed_pairs"] = []
                    b_state["policy_violations"] = []
                    core.save_batch_state(b_state)

            self.render_problems_view()
            self.update_problems_badge()
            self.render_now_card()
            self.render_all_pairs_card()
            self.render_saved_progress_card()
            self.update_overview_panel()
        except Exception as e:
            messagebox.showwarning("Notice", f"Could not clear problem for {script_name}: {e}")

    def skip_problem_script(self, script_path, script_name):
        """Moves the failed script to completed/ so it no longer blocks the queue."""
        p = Path(script_path)
        if not p.exists() and (self.scripts_dir / "completed" / p.name).exists():
            p = self.scripts_dir / "completed" / p.name
        elif p.exists() and p.parent.resolve() == self.scripts_dir.resolve():
            core._move_script_to_completed(str(p), self.ui)
        stem = Path(script_name).stem
        st_file = core.SCRIPT_STATES_DIR / f"{stem}_state.json"
        if st_file.exists():
            try:
                st_data = json.loads(st_file.read_text(encoding="utf-8"))
                st_data["status"] = "skipped"
                st_file.write_text(json.dumps(st_data, indent=2), encoding="utf-8")
            except Exception:
                pass
        self.refresh_scripts_list()
        self.render_problems_view()
        self.render_now_card()

    def clear_resolved_problems(self):
        """Clears all logged failures, policy violation records, and resets problem states across all scripts."""
        try:
            if core.POLICY_LOGS_FILE.exists():
                try:
                    core.POLICY_LOGS_FILE.unlink()
                except Exception:
                    pass
            if core.POLICY_LOGS_TXT.exists():
                try:
                    core.POLICY_LOGS_TXT.unlink()
                except Exception:
                    pass

            if core.SCRIPT_STATES_DIR.exists():
                for f in core.SCRIPT_STATES_DIR.glob("*_failures.txt"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
                for sf in core.SCRIPT_STATES_DIR.glob("*_state.json"):
                    try:
                        data = json.loads(sf.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            data["failed_pairs"] = []
                            data["policy_violations"] = []
                            if data.get("status") == "completed_with_errors":
                                data["status"] = "completed"
                            sf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass

            b_state = core.load_batch_state()
            if b_state and isinstance(b_state, dict):
                b_state["failed_pairs"] = []
                b_state["policy_violations"] = []
                if b_state.get("status") == "completed_with_errors":
                    b_state["status"] = "stopped"
                core.save_batch_state(b_state)

            self.current_error = None
            self.skipped_count = 0
            for i, stg in self.pair_stages.items():
                if stg.get("image") == "err":
                    stg["image"] = "wait"
                if stg.get("video") == "err":
                    stg["video"] = "wait"

            self.render_problems_view()
            self.update_problems_badge()
            self.render_now_card()
            self.render_all_pairs_card()
            self.render_saved_progress_card()
            self.update_overview_panel()
            messagebox.showinfo("Problems Cleared", "All problem logs and error records have been cleared.")
        except Exception as e:
            messagebox.showwarning("Notice", f"Could not clear all records: {e}")

    # ------------------------------------------------------------- VIEW 3: SCRIPTS & PROMPTS
    def _build_view_prompts(self):
        view = ctk.CTkScrollableFrame(self.view_container, fg_color="transparent")

        # Head row
        head = ctk.CTkFrame(view, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 14))

        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="Scripts & Prompts", font=("Segoe UI Variable", 28, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(titles, text="Everything about what gets generated lives here.", font=("Segoe UI Variable", 13), text_color=TOKEN_SUB, anchor="w").pack(fill="x", pady=(2, 0))

        # 1. Card: How scripts work (3-column guide)
        c_how = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        c_how.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(c_how, text="How scripts work", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=18, pady=(12, 6))

        how_grid = ctk.CTkFrame(c_how, fg_color="transparent")
        how_grid.pack(fill="x", padx=14, pady=(0, 14))
        how_grid.columnconfigure(0, weight=1)
        how_grid.columnconfigure(1, weight=1)
        how_grid.columnconfigure(2, weight=1)

        def add_how_step(col_idx, step_num, title, desc):
            f = ctk.CTkFrame(how_grid, fg_color="transparent")
            f.grid(row=0, column=col_idx, sticky="nsew", padx=6)
            ctk.CTkLabel(f, text=f"{step_num}. {title}", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
            ctk.CTkLabel(f, text=desc, font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w", justify="left").pack(fill="x", pady=(2, 0))

        add_how_step(0, 1, "Add", "Paste your .md script files into the scripts folder.")
        add_how_step(1, 2, "Choose", "Pick the script to run below. Each has up to 8 pairs.")
        add_how_step(2, 3, "Run", "Press Start batch. Finished scripts move to “completed”.")

        # 2. Card: Scripts folder
        c_folder = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        c_folder.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(c_folder, text="Scripts folder", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=18, pady=(12, 6))

        # Item 1: Folder path
        rf1 = ctk.CTkFrame(c_folder, fg_color="transparent")
        rf1.pack(fill="x", padx=18, pady=8)
        ctk.CTkLabel(rf1, text="scripts/", font=("Consolas", 12), fg_color=TOKEN_FILL, corner_radius=8, padx=10, pady=4).pack(side="left")

        b_open_f = ctk.CTkButton(rf1, text="Open folder", width=86, height=30, corner_radius=8, fg_color=TOKEN_ACC, text_color="#FFFFFF", font=("Segoe UI Variable", 12, "bold"), command=self.open_scripts_folder)
        b_open_f.pack(side="right", padx=(4, 0))
        CTkToolTip(b_open_f, "Opens the scripts folder in Explorer.")

        b_browse = ctk.CTkButton(rf1, text="Browse…", width=75, height=30, corner_radius=8, fg_color=TOKEN_FILL, text_color=TOKEN_TEXT, hover_color=TOKEN_LINE, font=("Segoe UI Variable", 12, "bold"), command=self.browse_script_file)
        b_browse.pack(side="right", padx=4)
        CTkToolTip(b_browse, "Choose a script from anywhere on your computer.")

        # Item 2: Active script picker
        rf2 = ctk.CTkFrame(c_folder, fg_color="transparent")
        rf2.pack(fill="x", padx=18, pady=(8, 14))
        l2 = ctk.CTkFrame(rf2, fg_color="transparent")
        l2.pack(side="left")
        ctk.CTkLabel(l2, text="Active script", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        self.lbl_scripts_count_sub = ctk.CTkLabel(l2, text="0 scripts waiting in the folder.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w")
        self.lbl_scripts_count_sub.pack(fill="x")

        box2 = ctk.CTkFrame(rf2, fg_color="transparent")
        box2.pack(side="right")

        self.script_combo_var = ctk.StringVar()
        self.script_menu = ctk.CTkOptionMenu(
            box2,
            variable=self.script_combo_var,
            values=["No scripts"],
            width=220,
            height=30,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            button_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            dropdown_fg_color=TOKEN_CARD,
            dropdown_text_color=TOKEN_TEXT,
            font=("Segoe UI Variable", 12),
            command=lambda v: self.load_selected_script(),
        )
        self.script_menu.pack(side="left", padx=4)

        b_load = ctk.CTkButton(box2, text="Load", width=56, height=30, corner_radius=8, fg_color=TOKEN_FILL, text_color=TOKEN_TEXT, hover_color=TOKEN_LINE, font=("Segoe UI Variable", 12, "bold"), command=self.load_selected_script)
        b_load.pack(side="left", padx=4)
        CTkToolTip(b_load, "Loads the selected script's prompt pairs.")

        b_refresh = ctk.CTkButton(box2, text="Refresh", width=68, height=30, corner_radius=8, fg_color=TOKEN_FILL, text_color=TOKEN_TEXT, hover_color=TOKEN_LINE, font=("Segoe UI Variable", 12, "bold"), command=self.refresh_scripts_list)
        b_refresh.pack(side="left", padx=4)
        CTkToolTip(b_refresh, "Rescans the scripts folder for new files.")

        # 3. Card: Script behavior
        c_beh = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        c_beh.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(c_beh, text="Script behavior", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=18, pady=(12, 6))

        # Row 1: Auto-advance switch
        rb1 = ctk.CTkFrame(c_beh, fg_color="transparent")
        rb1.pack(fill="x", padx=18, pady=8)
        lb1 = ctk.CTkFrame(rb1, fg_color="transparent")
        lb1.pack(side="left")
        ctk.CTkLabel(lb1, text="Start the next script automatically", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(lb1, text="Begins when the current script finishes.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
        self.auto_advance_var = ctk.BooleanVar(value=self.cfg.get("auto_advance_queue", True))
        ctk.CTkSwitch(rb1, text="", variable=self.auto_advance_var, width=42, height=24, progress_color=TOKEN_OK, command=self.save_settings).pack(side="right")

        # Row 2: Move completed switch
        rb2 = ctk.CTkFrame(c_beh, fg_color="transparent")
        rb2.pack(fill="x", padx=18, pady=8)
        lb2 = ctk.CTkFrame(rb2, fg_color="transparent")
        lb2.pack(side="left")
        ctk.CTkLabel(lb2, text="Move finished scripts to “completed”", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(lb2, text="Keeps the scripts folder tidy.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
        self.move_when_done_var = ctk.BooleanVar(value=self.cfg.get("move_script_when_done", True))
        ctk.CTkSwitch(rb2, text="", variable=self.move_when_done_var, width=42, height=24, progress_color=TOKEN_OK, command=self.save_settings).pack(side="right")

        # Row 3: Videos per script
        rb3 = ctk.CTkFrame(c_beh, fg_color="transparent")
        rb3.pack(fill="x", padx=18, pady=(8, 14))
        lb3 = ctk.CTkFrame(rb3, fg_color="transparent")
        lb3.pack(side="left")
        ctk.CTkLabel(lb3, text="Videos per script", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(lb3, text="The next script starts after this many.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
        self.videos_per_script_var = ctk.StringVar(value=str(self.cfg.get("videos_per_script", 8)))
        self.vars["videos_per_script"] = self.videos_per_script_var
        ctk.CTkEntry(rb3, textvariable=self.videos_per_script_var, width=84, height=30, corner_radius=8, fg_color=TOKEN_FILL, border_color=TOKEN_LINE, text_color=TOKEN_TEXT, font=("Segoe UI Variable", 12)).pack(side="right")

        # 4. Prompt pairs section header
        p_head = ctk.CTkFrame(view, fg_color="transparent")
        p_head.pack(fill="x", padx=24, pady=(20, 10))

        ctk.CTkLabel(p_head, text="Prompt pairs", font=("Segoe UI Variable", 20, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(side="left")

        p_btns = ctk.CTkFrame(p_head, fg_color="transparent")
        p_btns.pack(side="right")

        btn_clear = ctk.CTkButton(
            p_btns,
            text="Clear all",
            width=76,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            text_color=TOKEN_BAD,
            hover_color=TOKEN_FILL,
            font=("Segoe UI Variable", 12, "bold"),
            command=self.clear_rows,
        )
        btn_clear.pack(side="left", padx=4)
        CTkToolTip(btn_clear, "Removes every pair from this script. Can't be undone.")

        btn_bulk = ctk.CTkButton(
            p_btns,
            text="Bulk add…",
            width=84,
            height=32,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 12, "bold"),
            command=self.bulk_add,
        )
        btn_bulk.pack(side="left", padx=4)
        CTkToolTip(btn_bulk, "Paste many pairs at once from clipboard.")

        btn_add = ctk.CTkButton(
            p_btns,
            text="Add pair",
            width=80,
            height=32,
            corner_radius=8,
            fg_color=TOKEN_ACC,
            text_color="#FFFFFF",
            hover_color=TOKEN_ACC_HOVER,
            font=("Segoe UI Variable", 12, "bold"),
            command=lambda: self.add_row(),
        )
        btn_add.pack(side="left", padx=4)

        # Scrollable pairs container
        self.prompts_scroll = ctk.CTkFrame(view, fg_color="transparent")
        self.prompts_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        return view

    def on_prompt_edited(self):
        self.update_overview_panel()
        self.render_all_pairs_card()

    # ------------------------------------------------------------- VIEW 4: CALIBRATE
    def _build_view_calibrate(self):
        view = ctk.CTkScrollableFrame(self.view_container, fg_color="transparent")

        # Head row
        head = ctk.CTkFrame(view, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 14))

        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(
            titles,
            text="Calibrate Flow",
            font=("Segoe UI Variable", 28, "bold"),
            text_color=TOKEN_TEXT,
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            titles,
            text="Map interface buttons and thumbnails so automation interacts reliably with Flow.",
            font=("Segoe UI Variable", 13),
            text_color=TOKEN_SUB,
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        # Top Action Buttons
        btn_box = ctk.CTkFrame(head, fg_color="transparent")
        btn_box.pack(side="right")

        ctk.CTkButton(
            btn_box,
            text="▶ Calibrate all",
            height=32,
            corner_radius=8,
            fg_color=TOKEN_ACC,
            text_color="#FFFFFF",
            hover_color=TOKEN_ACC_HOVER,
            font=("Segoe UI Variable", 12, "bold"),
            command=self.do_calibrate,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_box,
            text="🔍 Test on canvas",
            height=32,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 12, "bold"),
            command=lambda: self.run_task(core.test_all_selectors, self.current_cfg(), self.ui),
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_box,
            text="📄 View selectors",
            height=32,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 12, "bold"),
            command=self.open_selectors_file,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_box,
            text="↺ Reset",
            height=32,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_WARN,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 12, "bold"),
            command=self.reset_selectors,
        ).pack(side="left", padx=4)

        # 1. System Health & Readiness Card
        self.calib_health_card = ctk.CTkFrame(
            view,
            fg_color=TOKEN_CARD,
            border_color=TOKEN_LINE,
            border_width=1,
            corner_radius=14,
        )
        self.calib_health_card.pack(fill="x", padx=24, pady=8)

        hh_row = ctk.CTkFrame(self.calib_health_card, fg_color="transparent")
        hh_row.pack(fill="x", padx=18, pady=(16, 6))

        tile = ctk.CTkFrame(hh_row, width=40, height=40, corner_radius=10, fg_color=("#0071E3", "#0A84FF"))
        tile.pack(side="left")
        tile.pack_propagate(False)
        ctk.CTkLabel(tile, text="🎯", font=("Segoe UI", 18), text_color="#FFFFFF").pack(expand=True)

        ht_titles = ctk.CTkFrame(hh_row, fg_color="transparent")
        ht_titles.pack(side="left", padx=12, fill="x", expand=True)

        self.calib_health_title = ctk.CTkLabel(
            ht_titles,
            text="Controls Readiness",
            font=("Segoe UI Variable", 16, "bold"),
            text_color=TOKEN_TEXT,
            anchor="w",
        )
        self.calib_health_title.pack(fill="x")

        self.calib_health_sub = ctk.CTkLabel(
            ht_titles,
            text="Checking calibrated controls...",
            font=("Segoe UI Variable", 12),
            text_color=TOKEN_SUB,
            anchor="w",
        )
        self.calib_health_sub.pack(fill="x")

        self.calib_status_badge = ctk.CTkLabel(
            hh_row,
            text="Checking",
            font=("Segoe UI Variable", 12, "bold"),
            fg_color=TOKEN_FILL,
            text_color=TOKEN_SUB,
            corner_radius=12,
            padx=12,
            pady=4,
        )
        self.calib_status_badge.pack(side="right")

        self.calib_progress_bar = ctk.CTkProgressBar(
            self.calib_health_card,
            height=6,
            corner_radius=3,
            progress_color=TOKEN_OK,
            fg_color=TOKEN_FILL,
        )
        self.calib_progress_bar.pack(fill="x", padx=18, pady=(8, 14))
        self.calib_progress_bar.set(0)

        # 2. Controls Catalogue Card
        cat_card = ctk.CTkFrame(
            view,
            fg_color=TOKEN_CARD,
            border_color=TOKEN_LINE,
            border_width=1,
            corner_radius=14,
        )
        cat_card.pack(fill="x", padx=24, pady=8)

        cat_hdr = ctk.CTkFrame(cat_card, fg_color="transparent")
        cat_hdr.pack(fill="x", padx=18, pady=(14, 8))
        ctk.CTkLabel(
            cat_hdr,
            text="Controls Catalogue",
            font=("Segoe UI Variable", 14, "bold"),
            text_color=TOKEN_TEXT,
            anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            cat_hdr,
            text="Click 'Recalibrate' on any individual item if Flow changes or fails to find that button.",
            font=("Segoe UI Variable", 12),
            text_color=TOKEN_SUB,
            anchor="e",
        ).pack(side="right")

        self.calib_control_defs = [
            ("image_prompt_box", "💬", "Image Prompt Box", "Required",
             "Text input box where you enter the description for generating a new image."),
            ("image_generate", "⚡", "Image Generate Button", "Required",
             "Button that initiates generation of the new image."),
            ("image_result", "🖼", "Generated Image Card / Tile", "Required (Multi)",
             "Generated image preview card on canvas clicked to detect when generation is complete."),
            ("project_more_options", "⋯", "Project Header 3-Dots (Ignore)", "Recommended",
             "Top toolbar three-dot button mapped so automation will NEVER click it by mistake."),
            ("video_mode_menu", "⋮", "Image Card 3-Dots Menu", "Required",
             "Options button on the generated image card (hover over image to reveal it)."),
            ("video_mode", "🎬", "Video Mode / 'Add to prompt'", "Required",
             "Context menu item clicked to transition the image into video generation mode."),
            ("video_prompt_box", "✏", "Video Prompt Box", "Required",
             "Text input box where you enter video motion, camera, or scene prompts."),
            ("video_generate", "🚀", "Video Generate Button", "Required",
             "Button that initiates generation of the new video."),
            ("video_result", "🎥", "Generated Video Card / Tile", "Required (Multi)",
             "Generated video preview card on canvas clicked to detect when video finishes."),
        ]

        self.calib_control_widgets = {}

        for idx, (key, glyph, title, req_lbl, desc) in enumerate(self.calib_control_defs):
            row = ctk.CTkFrame(cat_card, fg_color=TOKEN_FILL if idx % 2 == 1 else "transparent", corner_radius=8)
            row.pack(fill="x", padx=12, pady=3)

            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", padx=10, pady=8, fill="x", expand=True)

            title_row = ctk.CTkFrame(left, fg_color="transparent")
            title_row.pack(fill="x")

            ctk.CTkLabel(title_row, text=glyph, font=("Segoe UI", 14), width=22).pack(side="left")
            ctk.CTkLabel(title_row, text=title, font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT).pack(side="left", padx=6)

            is_req = "Required" in req_lbl
            badge_fg = TOKEN_ACC if is_req else TOKEN_LINE
            badge_tc = "#FFFFFF" if is_req else TOKEN_SUB
            ctk.CTkLabel(
                title_row,
                text=req_lbl,
                font=("Segoe UI Variable", 10, "bold"),
                fg_color=badge_fg,
                text_color=badge_tc,
                corner_radius=6,
                padx=6,
                pady=1,
            ).pack(side="left", padx=4)

            ctk.CTkLabel(left, text=desc, font=("Segoe UI Variable", 11), text_color=TOKEN_SUB, anchor="w", wraplength=480).pack(fill="x", padx=(28, 0), pady=(2, 4))

            sel_entry = ctk.CTkEntry(
                left,
                font=("Consolas", 10),
                height=22,
                corner_radius=6,
                fg_color=TOKEN_CARD,
                border_color=TOKEN_LINE,
                border_width=1,
                text_color=TOKEN_TEXT,
            )
            sel_entry.pack(fill="x", padx=(28, 0), pady=(1, 2))
            sel_entry.configure(state="readonly")

            right = ctk.CTkFrame(row, fg_color="transparent")
            right.pack(side="right", padx=10, pady=8)

            chip = ctk.CTkLabel(
                right,
                text="Checking",
                font=("Segoe UI Variable", 11, "bold"),
                corner_radius=8,
                padx=8,
                pady=2,
            )
            chip.pack(side="left", padx=6)

            btn = ctk.CTkButton(
                right,
                text="Recalibrate",
                width=88,
                height=28,
                corner_radius=6,
                fg_color=TOKEN_FILL,
                text_color=TOKEN_ACC,
                hover_color=TOKEN_LINE,
                font=("Segoe UI Variable", 11, "bold"),
                command=lambda k=key: self.do_recalibrate_key(k),
            )
            btn.pack(side="left", padx=2)

            self.calib_control_widgets[key] = (sel_entry, chip, btn)

        ctk.CTkFrame(cat_card, height=10, fg_color="transparent").pack()

        # 3. Tips Card
        tips_card = ctk.CTkFrame(
            view,
            fg_color=TOKEN_CARD,
            border_color=TOKEN_LINE,
            border_width=1,
            corner_radius=14,
        )
        tips_card.pack(fill="x", padx=24, pady=(8, 24))

        ctk.CTkLabel(
            tips_card,
            text="💡 Helpful Tips for Flow Calibration",
            font=("Segoe UI Variable", 13, "bold"),
            text_color=TOKEN_TEXT,
            anchor="w",
        ).pack(fill="x", padx=18, pady=(12, 4))

        tips = [
            "• Hovering elements: In Google Flow, buttons such as the image card 3-dots only appear when hovering your mouse over the card.",
            "• Pause anytime: Press Alt+P or click the floating 'CALIBRATING' badge in Chrome to freely pan, zoom, or close popups without recording unwanted clicks.",
            "• One-click repair: If Google updates a button, you do NOT have to repeat all 8 steps. Simply click 'Recalibrate' next to that single button above.",
        ]
        for t in tips:
            ctk.CTkLabel(
                tips_card,
                text=t,
                font=("Segoe UI Variable", 12),
                text_color=TOKEN_SUB,
                anchor="w",
                wraplength=660,
                justify="left",
            ).pack(fill="x", padx=18, pady=2)

        ctk.CTkFrame(tips_card, height=10, fg_color="transparent").pack()

        return view

    def render_calibrate_view(self):
        if not hasattr(self, "calib_control_widgets"):
            return
        sels = core.load_selectors()
        req_keys = core.REQUIRED
        calibrated_count = sum(1 for k in req_keys if k in sels and sels[k])
        total_req = len(req_keys)

        self.calib_health_sub.configure(
            text=f"{calibrated_count} of {total_req} required controls mapped and ready."
        )
        frac = calibrated_count / total_req if total_req else 0
        self.calib_progress_bar.set(frac)

        if calibrated_count == total_req:
            self.calib_status_badge.configure(
                text="✓ Ready for generation",
                fg_color=("#E6F4EA", "#133E26"),
                text_color=TOKEN_OK,
            )
            self.calib_progress_bar.configure(progress_color=TOKEN_OK)
        else:
            remaining = total_req - calibrated_count
            self.calib_status_badge.configure(
                text=f"⚠ Incomplete ({remaining} unmapped)",
                fg_color=("#FFF8E1", "#332600"),
                text_color=TOKEN_WARN,
            )
            self.calib_progress_bar.configure(progress_color=TOKEN_WARN)

        for key, (sel_entry, chip, btn) in self.calib_control_widgets.items():
            val = sels.get(key, "")
            sel_entry.configure(state="normal")
            sel_entry.delete(0, "end")
            sel_entry.insert(0, val if val else "Not calibrated yet — click Recalibrate to map")
            sel_entry.configure(state="readonly")

            if val:
                chip.configure(
                    text="✓ Calibrated",
                    fg_color=("#E6F4EA", "#133E26"),
                    text_color=TOKEN_OK,
                )
                btn.configure(text="Recalibrate", fg_color=TOKEN_FILL, text_color=TOKEN_ACC)
            else:
                chip.configure(
                    text="⚠ Unmapped",
                    fg_color=("#FFF8E1", "#332600"),
                    text_color=TOKEN_WARN,
                )
                btn.configure(text="Calibrate", fg_color=TOKEN_ACC, text_color="#FFFFFF")

    def do_recalibrate_key(self, key):
        self.run_task(core.calibrate_single_step, self.current_cfg(), self.ui, key)

    def reset_selectors(self):
        if messagebox.askyesno("Reset Selectors", "Are you sure you want to delete selectors.json and reset all control mappings?"):
            try:
                if core.SELECTORS_FILE.exists():
                    core.SELECTORS_FILE.unlink()
                self.render_calibrate_view()
                self.update_overview_panel()
                messagebox.showinfo("Reset Complete", "All selectors have been reset.")
            except Exception as e:
                messagebox.showerror("Error", f"Could not reset selectors: {e}")

    # ------------------------------------------------------------- VIEW 5: SETTINGS
    def _build_view_settings(self):
        view = ctk.CTkScrollableFrame(self.view_container, fg_color="transparent")

        # Head row
        head = ctk.CTkFrame(view, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 14))
        ctk.CTkLabel(head, text="Settings", font=("Segoe UI Variable", 28, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(head, text="Most people never need to change these.", font=("Segoe UI Variable", 13), text_color=TOKEN_SUB, anchor="w").pack(fill="x", pady=(2, 0))

        if not hasattr(self, "vars") or self.vars is None:
            self.vars = {}

        def make_entry_row(parent, title, sub, key, default_val, width=300):
            rf = ctk.CTkFrame(parent, fg_color="transparent")
            rf.pack(fill="x", padx=18, pady=8)
            left = ctk.CTkFrame(rf, fg_color="transparent")
            left.pack(side="left")
            ctk.CTkLabel(left, text=title, font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
            if sub:
                ctk.CTkLabel(left, text=sub, font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
            v = ctk.StringVar(value=str(self.cfg.get(key, default_val)))
            self.vars[key] = v
            ent = ctk.CTkEntry(rf, textvariable=v, width=width, height=30, corner_radius=8, fg_color=TOKEN_FILL, border_color=TOKEN_LINE, text_color=TOKEN_TEXT, font=("Segoe UI Variable", 12))
            ent.pack(side="right")
            ent.bind("<FocusOut>", lambda e: self.save_settings())
            return ent

        # Group 1: Google Flow
        c_flow = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        c_flow.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(c_flow, text="Google Flow", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=18, pady=(12, 6))

        make_entry_row(c_flow, "Flow address", "", "flow_url", "https://labs.google/fx/tools/flow", 320)
        make_entry_row(c_flow, "Project canvas", "Where images and videos are created.", "project_url", "", 320)

        self.profile_dir_var = ctk.StringVar(value=str(self.cfg.get("profile_dir", "chrome_profile")))
        self.vars["profile_dir"] = self.profile_dir_var
        rf_p = ctk.CTkFrame(c_flow, fg_color="transparent")
        rf_p.pack(fill="x", padx=18, pady=8)
        ctk.CTkLabel(rf_p, text="Saved sign-in folder", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT).pack(side="left")
        ctk.CTkEntry(rf_p, textvariable=self.profile_dir_var, width=180, height=30, corner_radius=8, fg_color=TOKEN_FILL, border_color=TOKEN_LINE, text_color=TOKEN_TEXT, font=("Segoe UI Variable", 12)).pack(side="right")

        rf_sb = ctk.CTkFrame(c_flow, fg_color="transparent")
        rf_sb.pack(fill="x", padx=18, pady=(8, 14))
        lsb = ctk.CTkFrame(rf_sb, fg_color="transparent")
        lsb.pack(side="left")
        ctk.CTkLabel(lsb, text="Show the browser window", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(lsb, text="Turn off to run in the background.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
        self.show_browser_var = ctk.BooleanVar(value=self.cfg.get("show_browser_window", True))
        ctk.CTkSwitch(rf_sb, text="", variable=self.show_browser_var, width=42, height=24, progress_color=TOKEN_OK, command=self.save_settings).pack(side="right")

        # Group 2: Timing
        c_time = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        c_time.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(c_time, text="Timing", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=18, pady=(12, 6))

        make_entry_row(c_time, "Image timeout", "Seconds to wait before giving up.", "image_timeout", 120, 84)
        make_entry_row(c_time, "Video timeout", "Seconds to wait before giving up.", "video_timeout", 360, 84)
        make_entry_row(c_time, "Pause between pairs", "Seconds. Helps avoid rate limits.", "pause_between_pairs", 5, 84)

        # Group 3: Errors
        c_err = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        c_err.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(c_err, text="Errors", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=18, pady=(12, 6))

        # Row 1: On reject
        re1 = ctk.CTkFrame(c_err, fg_color="transparent")
        re1.pack(fill="x", padx=18, pady=8)
        le1 = ctk.CTkFrame(re1, fg_color="transparent")
        le1.pack(side="left")
        ctk.CTkLabel(le1, text="When a prompt is rejected", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(le1, text="For example a policy violation.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
        self.on_reject_var = ctk.StringVar(value=self.cfg.get("on_reject_action", "Ask me"))
        self.vars["on_reject_action"] = self.on_reject_var
        menu_rej = ctk.CTkOptionMenu(
            re1,
            variable=self.on_reject_var,
            values=["Ask me", "Skip the pair", "Stop the batch"],
            width=160,
            height=30,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            button_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            dropdown_fg_color=TOKEN_CARD,
            dropdown_text_color=TOKEN_TEXT,
            font=("Segoe UI Variable", 12),
            command=lambda v: self.save_settings(),
        )
        menu_rej.pack(side="right")

        # Row 2: Retries
        make_entry_row(c_err, "Retry a failed step", "Times before asking you.", "max_retries", 2, 84)

        # Row 3: Save progress auto
        re3 = ctk.CTkFrame(c_err, fg_color="transparent")
        re3.pack(fill="x", padx=18, pady=(8, 14))
        le3 = ctk.CTkFrame(re3, fg_color="transparent")
        le3.pack(side="left")
        ctk.CTkLabel(le3, text="Save progress automatically", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(le3, text="Lets you resume a script later.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
        self.save_progress_auto_var = ctk.BooleanVar(value=self.cfg.get("save_progress_auto", True))
        ctk.CTkSwitch(re3, text="", variable=self.save_progress_auto_var, width=42, height=24, progress_color=TOKEN_OK, command=self.save_settings).pack(side="right")

        # Group 4: Advanced
        c_adv = ctk.CTkFrame(view, fg_color=TOKEN_CARD, border_color=TOKEN_LINE, border_width=1, corner_radius=14)
        c_adv.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(c_adv, text="Advanced", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_SUB, anchor="w").pack(fill="x", padx=18, pady=(12, 6))

        # Row 1: Reload project
        self.reload_each = ctk.BooleanVar(value=self.cfg.get("reload_each_pair", False))
        r_t1 = ctk.CTkFrame(c_adv, fg_color="transparent")
        r_t1.pack(fill="x", padx=18, pady=8)
        l_t1 = ctk.CTkFrame(r_t1, fg_color="transparent")
        l_t1.pack(side="left")
        ctk.CTkLabel(l_t1, text="Reload project before each pair", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(l_t1, text="Clears the canvas between images.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
        ctk.CTkSwitch(r_t1, text="", variable=self.reload_each, width=42, height=24, progress_color=TOKEN_OK, command=self.save_settings).pack(side="right")

        # Row 2: Test mode
        self.skip_image_gen = ctk.BooleanVar(value=self.cfg.get("skip_image_gen", False))
        r_t2 = ctk.CTkFrame(c_adv, fg_color="transparent")
        r_t2.pack(fill="x", padx=18, pady=8)
        l_t2 = ctk.CTkFrame(r_t2, fg_color="transparent")
        l_t2.pack(side="left")
        ctk.CTkLabel(l_t2, text="Test mode: skip image generation", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(l_t2, text="Uses the image already on the canvas.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")
        ctk.CTkSwitch(r_t2, text="", variable=self.skip_image_gen, width=42, height=24, progress_color=TOKEN_OK, command=lambda: [self.save_settings(), self.update_overview_panel()]).pack(side="right")

        # Row 3: Recalibrate one control
        rf_rep = ctk.CTkFrame(c_adv, fg_color="transparent")
        rf_rep.pack(fill="x", padx=18, pady=(8, 14))
        l_rep = ctk.CTkFrame(rf_rep, fg_color="transparent")
        l_rep.pack(side="left")
        ctk.CTkLabel(l_rep, text="Recalibrate one control", font=("Segoe UI Variable", 13, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(l_rep, text="Use when a single step stops working.", font=("Segoe UI Variable", 12), text_color=TOKEN_SUB, anchor="w").pack(fill="x")

        box_rep = ctk.CTkFrame(rf_rep, fg_color="transparent")
        box_rep.pack(side="right")

        self.step_options = [
            ("video_mode_menu", "Video mode menu"),
            ("video_mode", "Video mode (Add to prompt)"),
            ("image_result", "Image result thumbnail"),
            ("video_result", "Video result thumbnail"),
            ("image_prompt_box", "Image prompt box"),
            ("image_generate", "Image generate button"),
            ("video_prompt_box", "Video prompt box"),
            ("video_generate", "Video generate button"),
            ("project_more_options", "Project header 3-dots"),
        ]
        self.step_display_to_key = {disp: key for key, disp in self.step_options}
        self.recal_var = ctk.StringVar(value=self.step_options[0][1])
        menu_rep = ctk.CTkOptionMenu(
            box_rep,
            variable=self.recal_var,
            values=[disp for _, disp in self.step_options],
            width=200,
            height=30,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            button_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            dropdown_fg_color=TOKEN_CARD,
            dropdown_text_color=TOKEN_TEXT,
            font=("Segoe UI Variable", 12),
        )
        menu_rep.pack(side="left", padx=4)

        b_recal = ctk.CTkButton(box_rep, text="Recalibrate", width=86, height=30, corner_radius=8, fg_color=TOKEN_ACC, text_color="#FFFFFF", font=("Segoe UI Variable", 12, "bold"), command=self.do_recalibrate_single)
        b_recal.pack(side="left", padx=3)

        b_view_sels = ctk.CTkButton(box_rep, text="View selectors", width=95, height=30, corner_radius=8, fg_color=TOKEN_FILL, text_color=TOKEN_TEXT, hover_color=TOKEN_LINE, font=("Segoe UI Variable", 12, "bold"), command=self.open_selectors_file)
        b_view_sels.pack(side="left", padx=3)

        b_tab_calib = ctk.CTkButton(
            box_rep,
            text="Open Calibrate tab",
            width=130,
            height=30,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_ACC,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 12, "bold"),
            command=lambda: self.switch_view("calibrate"),
        )
        b_tab_calib.pack(side="left", padx=3)

        return view

    # ------------------------------------------------------------- VIEW 6: LOGS
    def _build_view_logs(self):
        view = ctk.CTkFrame(self.view_container, fg_color="transparent")

        # Head row
        head = ctk.CTkFrame(view, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 14))

        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="Logs", font=("Segoe UI Variable", 28, "bold"), text_color=TOKEN_TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(titles, text="What the app is doing, in plain language.", font=("Segoe UI Variable", 13), text_color=TOKEN_SUB, anchor="w").pack(fill="x", pady=(2, 0))

        # Actions & Filter
        btn_box = ctk.CTkFrame(head, fg_color="transparent")
        btn_box.pack(side="right")

        self.log_mode_seg = ctk.CTkSegmentedButton(
            btn_box,
            values=["Simple", "Detailed"],
            height=28,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            selected_color=TOKEN_CARD,
            selected_hover_color=TOKEN_CARD,
            unselected_color=TOKEN_FILL,
            unselected_hover_color=TOKEN_LINE,
            text_color=TOKEN_TEXT,
            font=("Segoe UI Variable", 12, "bold"),
            command=self.on_log_mode_changed,
        )
        self.log_mode_seg.set("Simple")
        self.log_mode_seg.pack(side="left", padx=6)

        b_copy = ctk.CTkButton(btn_box, text="Copy", width=56, height=28, corner_radius=6, fg_color=TOKEN_FILL, text_color=TOKEN_TEXT, hover_color=TOKEN_LINE, font=("Segoe UI Variable", 12, "bold"), command=self.copy_log_text)
        b_copy.pack(side="left", padx=3)

        b_clear = ctk.CTkButton(btn_box, text="Clear", width=56, height=28, corner_radius=6, fg_color=TOKEN_FILL, text_color=TOKEN_TEXT, hover_color=TOKEN_LINE, font=("Segoe UI Variable", 12, "bold"), command=self.clear_log)
        b_clear.pack(side="left", padx=3)

        b_file = ctk.CTkButton(btn_box, text="Open file", width=76, height=28, corner_radius=6, fg_color=TOKEN_FILL, text_color=TOKEN_TEXT, hover_color=TOKEN_LINE, font=("Segoe UI Variable", 12, "bold"), command=self.open_logs_folder)
        b_file.pack(side="left", padx=3)

        b_policy = ctk.CTkButton(btn_box, text="Policy warnings", width=110, height=28, corner_radius=6, fg_color=TOKEN_FILL, text_color=TOKEN_TEXT, hover_color=TOKEN_LINE, font=("Segoe UI Variable", 12, "bold"), command=self.open_policy_warnings)
        b_policy.pack(side="left", padx=3)

        # Monospace Log Console
        self.log_box = ctk.CTkTextbox(
            view,
            fg_color=TOKEN_CARD,
            border_color=TOKEN_LINE,
            border_width=1,
            corner_radius=14,
            text_color=TOKEN_TEXT,
            font=("Consolas", 12),
            wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        return view

    def on_log_mode_changed(self, val):
        self.log_mode = "easy" if val == "Simple" else "detailed"
        self._rerender_logs()

    def _rerender_logs(self):
        self.log_box.delete("1.0", "end")
        for raw_msg, is_easy in self.all_logs:
            if self.log_mode == "detailed" or (self.log_mode == "easy" and is_easy):
                self.log_box.insert("end", raw_msg + "\n")
        self.log_box.see("end")

    # ------------------------------------------------------------- ROWS & PAIRS MANAGEMENT
    def add_row(self, img="", vid=""):
        idx = len(self.rows) + 1
        r = PairRow(self, self.prompts_scroll, idx, img, vid)
        self.rows.append(r)
        self.renumber()

    def remove_row(self, row):
        if len(self.rows) <= 1:
            return
        row.frame.destroy()
        self.rows.remove(row)
        self.renumber()

    def clear_rows(self):
        if messagebox.askyesno("Clear Prompts", "Remove all prompt pairs from this script?"):
            for r in self.rows:
                r.frame.destroy()
            self.rows = []
            self.add_row()

    def renumber(self):
        for i, r in enumerate(self.rows, 1):
            r.set_index(i)
        self.total_pairs = len(self.rows)
        self.update_overview_panel()
        self.render_all_pairs_card()

    def bulk_add(self):
        win = ctk.CTkToplevel(self.root)
        win.title("Bulk Add Prompts")
        win.geometry("720x520")
        win.attributes("-topmost", True)

        ctk.CTkLabel(
            win,
            text="Paste image prompts on the left and video prompts on the right (one per line, matching order):",
            font=("Segoe UI Variable", 13, "bold"),
            text_color=TOKEN_TEXT,
        ).pack(fill="x", padx=16, pady=12)

        grid_f = ctk.CTkFrame(win, fg_color="transparent")
        grid_f.pack(fill="both", expand=True, padx=16, pady=4)
        grid_f.columnconfigure(0, weight=1)
        grid_f.columnconfigure(1, weight=1)

        ctk.CTkLabel(grid_f, text="Image prompts (one per line)", font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_SUB).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(grid_f, text="Video prompts (one per line)", font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_SUB).grid(row=0, column=1, sticky="w")

        a = ctk.CTkTextbox(grid_f, height=280, font=("Segoe UI Variable", 12))
        b = ctk.CTkTextbox(grid_f, height=280, font=("Segoe UI Variable", 12))
        a.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=4)
        b.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=4)
        grid_f.rowconfigure(1, weight=1)

        def ok():
            ims = [x.strip() for x in a.get("1.0", "end").splitlines() if x.strip()]
            vds = [x.strip() for x in b.get("1.0", "end").splitlines() if x.strip()]
            self.rows = [r for r in self.rows if r.get() != ("", "")] or self.rows
            for r in list(self.rows):
                if r.get() == ("", ""):
                    r.frame.destroy()
                    self.rows.remove(r)
            for i, v in zip_longest(ims, vds, fillvalue=""):
                self.add_row(i, v)
            win.destroy()

        btn_bar = ctk.CTkFrame(win, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(btn_bar, text="Import Prompts", fg_color=TOKEN_ACC, text_color="#FFFFFF", font=("Segoe UI Variable", 13, "bold"), command=ok).pack(side="right")
        ctk.CTkButton(btn_bar, text="Cancel", fg_color=TOKEN_FILL, text_color=TOKEN_TEXT, font=("Segoe UI Variable", 13), command=win.destroy).pack(side="right", padx=8)

    # ------------------------------------------------------------- SCRIPT QUEUE
    def refresh_scripts_list(self):
        files = []
        if self.scripts_dir.exists():
            for f in sorted(self.scripts_dir.glob("*.md")) + sorted(self.scripts_dir.glob("*.txt")):
                if f.is_file() and f.parent == self.scripts_dir:
                    files.append(f.name)
        self.pending_scripts = len(files)
        if hasattr(self, "script_menu"):
            self.script_menu.configure(values=files if files else ["No scripts found"])
        if hasattr(self, "lbl_scripts_count_sub"):
            self.lbl_scripts_count_sub.configure(text=f"{self.pending_scripts} scripts waiting in the folder.")

        if files:
            current = self.script_combo_var.get()
            if current in files:
                self.script_combo_var.set(current)
                if not self.current_script_path or not self.current_script_path.exists() or self.current_script_path.parent.name == "completed":
                    self.current_script_path = self.scripts_dir / current
            elif "dynamite-script.md" in files:
                self.script_combo_var.set("dynamite-script.md")
                if not self.current_script_path or not self.current_script_path.exists() or self.current_script_path.parent.name == "completed":
                    self.current_script_path = self.scripts_dir / "dynamite-script.md"
            elif "corn-flakes-script.md" in files:
                self.script_combo_var.set("corn-flakes-script.md")
                if not self.current_script_path or not self.current_script_path.exists() or self.current_script_path.parent.name == "completed":
                    self.current_script_path = self.scripts_dir / "corn-flakes-script.md"
            else:
                self.script_combo_var.set(files[0])
                if not self.current_script_path or not self.current_script_path.exists() or self.current_script_path.parent.name == "completed":
                    self.current_script_path = self.scripts_dir / files[0]
        else:
            self.script_combo_var.set("No scripts found")
            if not self.is_running and not self.batch_started:
                if self.current_script_path and (self.current_script_path.parent.name == "completed" or not self.current_script_path.exists()):
                    self.current_script_path = None
                    self.active_script_name = "None"

        self.update_script_status()

    def update_script_status(self):
        if not self.current_script_path:
            self.active_script_name = "None"
            self.update_overview_panel()
            if hasattr(self, "run_sub_lbl"):
                self.run_sub_lbl.configure(text="No script loaded · 0 pending scripts in queue.")
            return
        self.active_script_name = self.current_script_path.name
        self.update_overview_panel()
        if hasattr(self, "run_sub_lbl"):
            tot = max(1, len(self.rows))
            self.run_sub_lbl.configure(text=f"{self.active_script_name} · {tot} pairs. Each pair makes an image, then a video.")

    def load_selected_script(self):
        name = self.script_combo_var.get().strip()
        if not name or name == "No scripts found":
            messagebox.showinfo("Select Script", "Please select a script from the dropdown or click 'Browse…'.")
            return
        self.load_script_file(self.scripts_dir / name)

    def load_script_file(self, script_path, reset_state=True):
        p = Path(script_path)
        if not p.exists():
            messagebox.showerror("Not Found", f"Script file not found: {p}")
            return
        try:
            import import_script as importer
            pairs = importer.parse_script_file(p)
            if not pairs:
                messagebox.showwarning("No pairs found", f"Could not extract prompt pairs from {p.name}.")
                return
            pairs = pairs[:8]

            for r in list(self.rows):
                r.frame.destroy()
            self.rows = []
            for img, vid in pairs:
                self.add_row(img, vid)

            self.current_script_path = p
            slug = re.sub(r"[-_]script$", "", p.stem, flags=re.I) or p.stem
            out_dir = str(Path("output") / slug)
            if "output_dir" in self.vars:
                self.vars["output_dir"].set(out_dir)

            if reset_state:
                self.video_generated = 0
                self.skipped_count = 0
                self.current_pair_idx = 1
                self.init_pair_stages()
            self.save_settings()
            self.update_script_status()
            self.render_now_card()
            self.render_all_pairs_card()
            self.render_saved_progress_card()
            self.log(f"📂 Loaded script '{p.name}' ({len(pairs)} pairs). Output set to '{out_dir}/'.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load script: {e}")

    def browse_script_file(self):
        f = filedialog.askopenfilename(
            title="Select markdown script file",
            filetypes=[("Markdown files", "*.md"), ("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=str(self.scripts_dir),
        )
        if not f:
            return
        p = Path(f)
        if p.parent.resolve() != self.scripts_dir.resolve():
            dest = self.scripts_dir / p.name
            try:
                shutil.copy2(str(p), str(dest))
                p = dest
            except Exception:
                pass
        self.refresh_scripts_list()
        self.script_combo_var.set(p.name)
        self.load_script_file(p)

    def open_scripts_folder(self):
        try:
            os.startfile(str(self.scripts_dir))
        except Exception as e:
            messagebox.showinfo("Scripts folder", f"Location: {self.scripts_dir}\nError: {e}")

    # ------------------------------------------------------------- CONFIG & PERSISTENCE
    def current_cfg(self):
        cfg = dict(self.cfg)
        for k, v in self.vars.items():
            cfg[k] = v.get().strip() if hasattr(v, "get") else str(v)
        for k in ("image_timeout", "video_timeout", "pause_between_pairs", "max_retries", "videos_per_script"):
            if k in cfg:
                try:
                    cfg[k] = int(cfg[k])
                except ValueError:
                    cfg[k] = core.DEFAULTS.get(k, 0)

        cfg["reload_each_pair"] = self.reload_each.get()
        cfg["skip_image_gen"] = self.skip_image_gen.get()
        cfg["profile_dir"] = self.profile_dir_var.get().strip() or "chrome_profile"
        cfg["show_browser_window"] = self.show_browser_var.get()
        cfg["move_script_when_done"] = self.move_when_done_var.get()
        cfg["auto_advance_queue"] = self.auto_advance_var.get()
        cfg["on_reject_action"] = self.on_reject_var.get()
        cfg["save_progress_auto"] = self.save_progress_auto_var.get()
        cfg["script_file"] = str(self.current_script_path) if self.current_script_path else ""
        cfg["theme"] = self.theme_seg.get().lower()
        cfg["resume_pair_index"] = getattr(self, "current_pair_idx", 1)

        for dep in ["download_images", "download_videos", "image_name", "video_name", "video_format"]:
            cfg.pop(dep, None)

        return cfg

    def save_settings(self):
        data = {"cfg": self.current_cfg(), "pairs": [list(r.get()) for r in self.rows]}
        SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.update_overview_panel()

    def restore_saved_session_state(self):
        """Restores batch state from disk so progress survives restarts seamlessly."""
        try:
            state = core.load_batch_state()
            if not state:
                # If no pending scripts in scripts/ and not running, clear lingering completed script rows
                if self.pending_scripts == 0 and not self.is_running and not self.batch_started:
                    if not self.current_script_path or self.current_script_path.parent.name == "completed" or not self.current_script_path.exists():
                        self.current_script_path = None
                        self.active_script_name = "None"
                        for r in list(self.rows):
                            r.frame.destroy()
                        self.rows = []
                        self.add_row("", "")
                        self.init_pair_stages()
                        self.save_settings()
                self.render_now_card()
                self.render_all_pairs_card()
                self.render_saved_progress_card()
                self.update_overview_panel()
                return

            s_name = state.get("script_name", "")
            s_file = state.get("script_file", "")
            target_path = Path(s_file) if s_file else (self.scripts_dir / s_name if s_name else None)
            status = state.get("status", "")
            completed = state.get("completed_pairs", [])
            failed = state.get("failed_pairs", [])
            failed_nums = {f.get("pair") for f in failed if isinstance(f, dict) and f.get("pair")}
            completed = [c for c in completed if c not in failed_nums]

            # Check if this script was already cleanly completed (NO failed pairs) and moved to completed/
            is_in_completed = (target_path and target_path.parent.name == "completed") or (not target_path.exists() and (self.scripts_dir / "completed" / s_name).exists())
            if (status == "completed" and not failed_nums) or (is_in_completed and not failed_nums):
                core.clear_batch_state()
                # If there are pending files in scripts/, load the first
                pending = [f for f in sorted(self.scripts_dir.glob("*.md")) if f.is_file() and f.parent == self.scripts_dir]
                if pending:
                    self.load_script_file(pending[0], reset_state=True)
                else:
                    self.current_script_path = None
                    self.active_script_name = "None"
                    self.batch_started = False
                    self.video_generated = 0
                    self.skipped_count = 0
                    for r in list(self.rows):
                        r.frame.destroy()
                    self.rows = []
                    self.add_row("", "")
                    self.init_pair_stages()
                    self.save_settings()
                self.render_now_card()
                self.render_all_pairs_card()
                self.render_saved_progress_card()
                self.update_overview_panel()
                return

            # Script is NOT cleanly completed (e.g. stopped, interrupted, running, or has errors)
            if target_path and target_path.exists():
                self.load_script_file(target_path, reset_state=False)
            elif s_name and (self.scripts_dir / s_name).exists():
                self.load_script_file(self.scripts_dir / s_name, reset_state=False)
            elif s_name and (self.scripts_dir / "completed" / s_name).exists():
                self.load_script_file(self.scripts_dir / "completed" / s_name, reset_state=False)

            cur_idx = state.get("current_pair_index", 1)
            self.current_pair_idx = cur_idx
            self.video_generated = len(completed)
            self.skipped_count = len(failed_nums)

            for i in range(1, len(self.rows) + 1):
                if i in completed:
                    self.pair_stages[i] = {"image": "ok", "video": "ok"}
                elif i in failed_nums:
                    self.pair_stages[i] = {"image": "err", "video": "err"}
                else:
                    self.pair_stages[i] = {"image": "wait", "video": "wait"}

            for f in failed:
                p_num = f.get("pair")
                stg = f.get("stage", "image")
                if p_num:
                    self.current_error = {
                        "pair": p_num,
                        "stage": stg,
                        "code": "policy_violation" if "Policy" in f.get("reason", "") else "error",
                        "message": f.get("reason", ""),
                        "image_prompt": f.get("image_prompt", ""),
                        "video_prompt": f.get("video_prompt", ""),
                        "script_name": s_name,
                        "script_file": str(target_path) if target_path else "",
                    }

            if status in ["stopped", "running", "interrupted", "completed_with_errors"] or (cur_idx > 1 and len(completed) < len(self.rows)) or failed:
                self.batch_started = True
                self.btn_start.configure(state="normal", text="▶ Resume batch")
                self.btn_stop.configure(state="disabled")

            self.render_now_card()
            self.render_all_pairs_card()
            self.render_saved_progress_card()
            self.update_overview_panel()
        except Exception as e:
            self.log(f"Notice: Failed to restore previous session state: {e}")

    def open_inspect_error_modal(self, err_data=None):
        """Opens a modal dialog showing full error details and editable Image/Video prompts for the failed pair."""
        if not err_data:
            err_data = self.current_error or {}

        pair_num = err_data.get("pair", self.current_pair_idx)
        stage = err_data.get("stage", "image")
        reason = err_data.get("message") or err_data.get("reason", "Unknown policy or generation issue")

        # Get existing prompt text from row or error dict
        cur_row = self.rows[pair_num - 1] if pair_num <= len(self.rows) else None
        img_p, vid_p = cur_row.get() if cur_row else ("", "")
        if not img_p and err_data.get("image_prompt"):
            img_p = err_data.get("image_prompt")
        if not vid_p and err_data.get("video_prompt"):
            vid_p = err_data.get("video_prompt")

        s_name = err_data.get("script_name") or (self.current_script_path.name if self.current_script_path else "Current Script")

        win = ctk.CTkToplevel(self.root)
        win.title(f"Inspect Error & Prompts — Pair #{pair_num}")
        win.geometry("780x640")
        win.attributes("-topmost", True)

        head_f = ctk.CTkFrame(win, fg_color="transparent")
        head_f.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            head_f,
            text=f"Prompt Failure Inspector · Pair #{pair_num}",
            font=("Segoe UI Variable", 16, "bold"),
            text_color=TOKEN_TEXT,
            anchor="w"
        ).pack(fill="x")
        ctk.CTkLabel(
            head_f,
            text=f"Script: {s_name}  |  Stage: {stage.capitalize()} generation",
            font=("Segoe UI Variable", 12),
            text_color=TOKEN_SUB,
            anchor="w"
        ).pack(fill="x", pady=(2, 0))

        # Error Details Box
        err_box = ctk.CTkFrame(win, fg_color=("#FFF1F2", "#3B181A"), border_color=("#FECDD3", "#991B1B"), border_width=1, corner_radius=10)
        err_box.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(
            err_box,
            text="Reason / Notice from Google Flow:",
            font=("Segoe UI Variable", 11, "bold"),
            text_color=TOKEN_BAD,
            anchor="w"
        ).pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            err_box,
            text=reason,
            font=("Consolas", 12),
            text_color=TOKEN_TEXT,
            anchor="w",
            wraplength=720,
            justify="left"
        ).pack(fill="x", padx=14, pady=(0, 10))

        # Prompts editor container
        body_f = ctk.CTkFrame(win, fg_color="transparent")
        body_f.pack(fill="both", expand=True, padx=20, pady=6)
        body_f.columnconfigure(0, weight=1)
        body_f.columnconfigure(1, weight=1)
        body_f.rowconfigure(1, weight=1)

        ctk.CTkLabel(body_f, text="Image Prompt (editable):", font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_TEXT).grid(row=0, column=0, sticky="w", pady=(0, 4))
        ctk.CTkLabel(body_f, text="Video Prompt (editable):", font=("Segoe UI Variable", 12, "bold"), text_color=TOKEN_TEXT).grid(row=0, column=1, sticky="w", pady=(0, 4))

        img_box = ctk.CTkTextbox(body_f, font=("Segoe UI Variable", 12), wrap="word")
        img_box.insert("1.0", img_p)
        img_box.grid(row=1, column=0, sticky="nsew", padx=(0, 6))

        vid_box = ctk.CTkTextbox(body_f, font=("Segoe UI Variable", 12), wrap="word")
        vid_box.insert("1.0", vid_p)
        vid_box.grid(row=1, column=1, sticky="nsew", padx=(6, 0))

        def save_and_edit_in_prompts():
            new_img = img_box.get("1.0", "end").strip()
            new_vid = vid_box.get("1.0", "end").strip()
            if cur_row:
                cur_row.img_box.delete("1.0", "end")
                cur_row.img_box.insert("1.0", new_img)
                cur_row.vid_box.delete("1.0", "end")
                cur_row.vid_box.insert("1.0", new_vid)
            self.save_settings()
            win.destroy()
            self.switch_view("prompts")
            self.log(f"📝 Loaded Pair #{pair_num} into Prompts Editor with your adjustments.")

        def save_and_retry():
            new_img = img_box.get("1.0", "end").strip()
            new_vid = vid_box.get("1.0", "end").strip()
            if cur_row:
                cur_row.img_box.delete("1.0", "end")
                cur_row.img_box.insert("1.0", new_img)
                cur_row.vid_box.delete("1.0", "end")
                cur_row.vid_box.insert("1.0", new_vid)
            self.save_settings()
            self.current_error = None
            win.destroy()
            if hasattr(self.ui, "user_decision"):
                self.ui.user_decision.put("retry")
            else:
                self.do_start(resume=True)
            self.render_now_card()

        # Action Buttons Row
        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(10, 16))

        ctk.CTkButton(
            bar,
            text="▶ Save & Retry Now",
            height=36,
            corner_radius=8,
            fg_color=TOKEN_ACC,
            text_color="#FFFFFF",
            font=("Segoe UI Variable", 12, "bold"),
            command=save_and_retry
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            bar,
            text="Load into Prompts Editor",
            height=36,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_TEXT,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 12, "bold"),
            command=save_and_edit_in_prompts
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            bar,
            text="Close",
            height=36,
            width=70,
            corner_radius=8,
            fg_color=TOKEN_FILL,
            text_color=TOKEN_SUB,
            hover_color=TOKEN_LINE,
            font=("Segoe UI Variable", 12),
            command=win.destroy
        ).pack(side="right")

    # ------------------------------------------------------------- ASYNC TASKS
    def run_task(self, fn, *args):
        if self.thread and self.thread.is_alive():
            messagebox.showinfo("Busy", "A task is already running. Press Stop first.")
            return
        self.save_settings()
        self.ui.stop.clear()
        self.ui.skip.clear()
        self.ui.paused.clear()
        self.pause_calib_btn.configure(text="Pause")
        self.is_running = True
        self.btn_start.configure(state="disabled")
        if hasattr(self, "btn_restart"):
            self.btn_restart.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.render_now_card()

        def wrapper():
            try:
                import importlib
                reloaded = importlib.reload(core)
                target_fn = getattr(reloaded, fn.__name__, fn) if hasattr(fn, "__name__") else fn
                target_fn(*args)
            except Exception as e:
                err_str = str(e)
                if isinstance(e, getattr(core, "Stopped", Exception)) or "Stopped" in type(e).__name__:
                    self.ui.log("⏹ Task stopped.")
                elif "TargetClosedError" in type(e).__name__ or "Target page, context or browser has been closed" in err_str:
                    self.ui.log("⏹ Browser window or page was closed. Task stopped cleanly.")
                else:
                    self.ui.log(traceback.format_exc())
            finally:
                self.q.put(("done", None))

        self.thread = threading.Thread(target=wrapper, daemon=True)
        self.thread.start()

    def do_login(self):
        self.run_task(core.login, self.current_cfg(), self.ui)

    def do_calibrate(self):
        self.run_task(core.calibrate, self.current_cfg(), self.ui)

    def do_recalibrate_single(self):
        disp = self.recal_var.get().strip()
        key = self.step_display_to_key.get(disp, disp.split()[0] if disp else "")
        if not key:
            messagebox.showwarning("No step", "Please select a step to recalibrate.")
            return
        self.run_task(core.calibrate_single_step, self.current_cfg(), self.ui, key)

    def open_selectors_file(self):
        try:
            if core.SELECTORS_FILE.exists():
                os.startfile(str(core.SELECTORS_FILE))
            else:
                messagebox.showinfo("selectors.json", "selectors.json has not been created yet.")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open selectors.json: {e}")

    def open_policy_warnings(self):
        txt_path = core.POLICY_LOGS_TXT
        json_path = core.POLICY_LOGS_FILE
        if txt_path.exists() and txt_path.stat().st_size > 0:
            try:
                os.startfile(str(txt_path))
            except Exception:
                try:
                    os.startfile(str(json_path))
                except Exception as e:
                    messagebox.showerror("Error", f"Could not open policy warnings log: {e}")
        else:
            messagebox.showinfo("Policy Warnings", "No policy violations recorded yet. All prompt pairs have passed safety checks.")

    def do_restart(self):
        """Restarts the active script from Pair #1, clearing all previous errors or saved progress for this script."""
        if self.is_running:
            messagebox.showinfo("Running", "Please stop the active batch before restarting.")
            return

        tot = max(1, len(self.rows))
        s_name = self.current_script_path.name if self.current_script_path else "the active script"
        ans = messagebox.askyesno(
            "Restart from Pair #1",
            f"Are you sure you want to restart '{s_name}' from Pair #1?\n\n"
            f"• All {tot} pairs will be generated fresh from the beginning.\n"
            f"• Notice: This will consume Google Flow generation tokens for all {tot} pairs.\n"
            f"• Any previous error, completed, or skipped states for this script will be permanently cleared.\n\n"
            f"Proceed with fresh restart from Pair #1?"
        )
        if not ans:
            return

        # 1. Ensure target script file is located in scripts/ (move back from completed/ if needed)
        target_script = self.current_script_path
        if target_script:
            if target_script.parent.name == "completed" and target_script.exists():
                dest = self.scripts_dir / target_script.name
                try:
                    shutil.move(str(target_script), str(dest))
                    target_script = dest
                except Exception:
                    pass
            elif not target_script.exists() and (self.scripts_dir / "completed" / target_script.name).exists():
                comp_file = self.scripts_dir / "completed" / target_script.name
                dest = self.scripts_dir / target_script.name
                try:
                    shutil.move(str(comp_file), str(dest))
                    target_script = dest
                except Exception:
                    pass
        else:
            pending = [f for f in sorted(self.scripts_dir.glob("*.md")) if f.is_file() and f.parent == self.scripts_dir]
            if pending:
                target_script = pending[0]
            else:
                comp = [f for f in sorted((self.scripts_dir / "completed").glob("*.md")) if f.is_file()]
                if comp:
                    dest = self.scripts_dir / comp[0].name
                    try:
                        shutil.move(str(comp[0]), str(dest))
                        target_script = dest
                    except Exception:
                        pass
        self.current_script_path = target_script

        core.clear_batch_state()
        if self.current_script_path:
            core.clear_script_state(self.current_script_path)
            rep_file = core.SCRIPT_STATES_DIR / f"{self.current_script_path.stem}_failures.txt"
            if rep_file.exists():
                try:
                    rep_file.unlink()
                except Exception:
                    pass

        # 2. Reload script cleanly from disk
        if self.current_script_path and self.current_script_path.exists():
            self.load_script_file(self.current_script_path, reset_state=True)
        else:
            self.current_pair_idx = 1
            self.video_generated = 0
            self.skipped_count = 0
            self.current_error = None
            self.batch_started = False
            self.init_pair_stages()

        self.current_pair_idx = 1
        self.video_generated = 0
        self.skipped_count = 0
        self.current_error = None
        self.batch_started = False
        self.init_pair_stages()

        if "resume_pair_index" in self.vars:
            self.vars["resume_pair_index"].set("1")
        cfg = self.current_cfg()
        cfg["resume_pair_index"] = 1
        if self.current_script_path:
            cfg["script_file"] = str(self.current_script_path)
        self.save_settings()

        self.render_now_card()
        self.render_all_pairs_card()
        self.render_saved_progress_card()
        self.update_overview_panel()
        self.update_problems_badge()
        self.log(f"🔄 Cleared saved progress for '{s_name}'. Restarting fresh from Pair #1 (will generate all {tot} pairs)...")
        self.do_start(resume=False)

    def do_start(self, resume=None):
        is_ready, missing, _ = self.check_setup_status()
        if not is_ready:
            msg = "Before running the batch, the following setup items are required:\n\n"
            for m in missing:
                msg += f"  • {m}\n"
            msg += "\nWould you like to open the Setup view now to configure them?"
            if messagebox.askyesno("Setup Required", msg):
                self.reopen_setup_wizard()
            return

        pairs = [r.get() for r in self.rows]
        pairs = [p for p in pairs if p != ("", "")]
        if not pairs:
            messagebox.showwarning("No prompts", "Paste at least one prompt pair.")
            return
        for i, (a, b) in enumerate(pairs, 1):
            if not a or not b:
                messagebox.showwarning("Incomplete", f"Pair #{i} needs BOTH an image prompt and a video prompt.")
                return

        cfg = self.current_cfg()
        if resume is None:
            state = core.load_batch_state()
            if not state and self.current_script_path:
                state = core.load_script_state(self.current_script_path)
            if state and (state.get("status") in ["stopped", "interrupted", "running", "completed_with_errors"] or state.get("failed_pairs")):
                cur_idx = state.get("current_pair_index", 1)
                tot = state.get("total_pairs", len(pairs))
                s_name = state.get("script_name", "")
                completed_list = state.get("completed_pairs", [])
                failed_list = state.get("failed_pairs", [])
                if cur_idx > 1 or failed_list:
                    ans = messagebox.askyesnocancel(
                        "Batch Progress Options",
                        f"Saved progress found for '{s_name}'.\n\n"
                        f"• Completed: {len(completed_list)} of {tot} videos\n"
                        f"• Issues/Skipped: {len(failed_list)} pairs\n\n"
                        f"Options:\n"
                        f"• Click 'Yes' to RESUME from Pair #{cur_idx} (preserves completed videos to save tokens)\n"
                        f"• Click 'No' to START FRESH from Pair #1 (regenerates all pairs from beginning; consumes tokens)\n"
                        f"• Click 'Cancel' to abort"
                    )
                    if ans is None:
                        return
                    resume = ans

        if resume:
            state = core.load_batch_state()
            cfg["resume_pair_index"] = state.get("current_pair_index", 1) if state else getattr(self, "current_pair_idx", 1)
        else:
            cfg["resume_pair_index"] = 1
            if "resume_pair_index" in self.vars:
                self.vars["resume_pair_index"].set("1")
            core.clear_batch_state()
            if self.current_script_path:
                core.clear_script_state(self.current_script_path)
                rep_file = core.SCRIPT_STATES_DIR / f"{self.current_script_path.stem}_failures.txt"
                if rep_file.exists():
                    try:
                        rep_file.unlink()
                    except Exception:
                        pass
                if self.current_script_path.parent.name == "completed":
                    dest = self.scripts_dir / self.current_script_path.name
                    try:
                        shutil.move(str(self.current_script_path), str(dest))
                        self.current_script_path = dest
                    except Exception:
                        pass
                elif not self.current_script_path.exists() and (self.scripts_dir / "completed" / self.current_script_path.name).exists():
                    comp_f = self.scripts_dir / "completed" / self.current_script_path.name
                    dest = self.scripts_dir / self.current_script_path.name
                    try:
                        shutil.move(str(comp_f), str(dest))
                        self.current_script_path = dest
                    except Exception:
                        pass
                if self.current_script_path.exists():
                    self.load_script_file(self.current_script_path, reset_state=True)
                    pairs = [r.get() for r in self.rows if r.get() != ("", "")]
            self.current_pair_idx = 1
            self.video_generated = 0
            self.skipped_count = 0
            self.current_error = None
            self.batch_started = False
            self.init_pair_stages()
            self.save_settings()
            self.render_now_card()
            self.render_all_pairs_card()
            self.render_saved_progress_card()
            self.update_overview_panel()
            self.update_problems_badge()

        self.batch_started = True
        self.current_error = None
        self.current_pair_idx = cfg["resume_pair_index"]
        self.run_task(core.run_batch, cfg, pairs, self.ui)

    def do_stop(self):
        self.ui.stop.set()
        self.is_running = False
        self.log("⏹ Stop requested by user. Progress saved.")
        self.btn_start.configure(state="normal", text="▶ Resume batch")
        if hasattr(self, "btn_restart"):
            self.btn_restart.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.render_now_card()
        self.render_saved_progress_card()

    def toggle_pause_calib(self):
        if self.ui.paused.is_set():
            self.ui.paused.clear()
            self.pause_calib_btn.configure(text="Pause")
            self.log("▶ Calibration resumed.")
        else:
            self.ui.paused.set()
            self.pause_calib_btn.configure(text="Resume")
            self.log("⏸ Calibration paused. Browser clicks will not be recorded until resumed.")

    # ------------------------------------------------------------- LOGGING
    def _is_easy_log(self, msg: str):
        m = msg.strip().lower()
        if not m:
            return False
        if "policy violation" in m or "resuming" in m or "all scripts finished" in m or "stopped" in m or "pair" in m:
            return True
        noisy = [
            "watching selector", "still waiting for", "hovering image tile", "found 3-dots button",
            "clicking 3-dots button", "image options menu is open", "selecting video mode",
            "dom logger notice", "launching playwright chromium", "extra seconds after",
            "locator.", "settle_video", "settle_image", "reconnecting project page",
            "dismiss_editor_overlay", "candidate selectors", "status check:",
        ]
        return not any(n in m for n in noisy)

    def log(self, msg):
        is_easy = self._is_easy_log(msg)
        self.all_logs.append((msg, is_easy))
        if self.log_mode == "detailed" or (self.log_mode == "easy" and is_easy):
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")

    def clear_log(self):
        self.all_logs.clear()
        self.log_box.delete("1.0", "end")

    def copy_log_text(self):
        text = self.log_box.get("1.0", "end")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("Copied", "Log output copied to clipboard.")

    def open_logs_folder(self):
        try:
            core.LOGS_DIR.mkdir(exist_ok=True)
            os.startfile(str(core.LOGS_DIR))
        except Exception as e:
            messagebox.showinfo("Logs folder", f"Location: {core.LOGS_DIR}\nError: {e}")

    # ------------------------------------------------------------- POLLING
    def poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.log(data)
                elif kind == "pause_state":
                    is_paused = data
                    self.is_paused = is_paused
                    if is_paused:
                        self.pause_calib_btn.configure(text="Resume")
                    else:
                        self.pause_calib_btn.configure(text="Pause")
                    self.render_now_card()
                elif kind == "step":
                    msg, show = data
                    if msg:
                        self.step_lbl.configure(text=msg)
                        self.alert_frame.pack(fill="x", padx=24, pady=(10, 4))
                        if show:
                            self.skip_btn.pack(side="right", padx=4)
                            self.pause_calib_btn.pack(side="right", padx=4)
                        else:
                            self.skip_btn.pack_forget()
                            self.pause_calib_btn.pack_forget()
                    else:
                        self.alert_frame.pack_forget()
                    self.render_calibrate_view()
                elif kind == "pair_stage":
                    n, stage, status = data
                    self.current_pair_idx = n
                    if n not in self.pair_stages:
                        self.pair_stages[n] = {"image": "wait", "video": "wait"}
                    self.pair_stages[n][stage] = status
                    self.render_now_card()
                    self.render_all_pairs_card()
                elif kind == "pair_error":
                    s_name, n, tot, stage, code, msg = data
                    self.current_pair_idx = n
                    self.current_error = {
                        "pair": n,
                        "stage": stage,
                        "code": code,
                        "message": msg,
                    }
                    if n not in self.pair_stages:
                        self.pair_stages[n] = {"image": "wait", "video": "wait"}
                    self.pair_stages[n][stage] = "err"
                    self.render_now_card()
                    self.render_all_pairs_card()
                    self.render_saved_progress_card()
                    self.render_problems_view()
                    self.update_problems_badge()
                elif kind == "ask_decision":
                    n, stage, msg = data
                    self.current_pair_idx = n
                    self.current_error = {
                        "pair": n,
                        "stage": stage,
                        "code": "policy_violation",
                        "message": msg,
                    }
                    self.render_now_card()
                    self.render_problems_view()
                    self.update_problems_badge()
                elif kind == "queue_progress":
                    script_name, video_gen, total_pairs, pending_count = data
                    self.video_generated = video_gen
                    self.total_pairs = total_pairs
                    self.pending_scripts = pending_count
                    if self.current_script_path is None or self.current_script_path.name != script_name:
                        target = self.scripts_dir / script_name
                        if target.exists():
                            self.load_script_file(target)
                    self.render_now_card()
                    self.render_all_pairs_card()
                    self.render_saved_progress_card()
                    self.update_overview_panel()
                elif kind == "done":
                    self.alert_frame.pack_forget()
                    self.is_running = False
                    is_complete = self.batch_started and (self.video_generated >= max(1, len(self.rows)))
                    btn_t = "Start batch" if is_complete else "▶ Resume batch"
                    self.btn_start.configure(state="normal", text=btn_t)
                    if hasattr(self, "btn_restart"):
                        self.btn_restart.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self.refresh_scripts_list()
                    self.render_now_card()
                    self.render_all_pairs_card()
                    self.render_saved_progress_card()
                    self.update_overview_panel()
                    self.render_problems_view()
                    self.update_problems_badge()
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def on_close(self):
        self.ui.stop.set()
        self.save_settings()
        self.root.destroy()


if __name__ == "__main__":
    root = ctk.CTk()
    App(root)
    root.mainloop()
