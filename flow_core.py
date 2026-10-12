"""Core automation engine: Chrome profile + Google Flow (image -> video).

All browser work happens in ONE worker thread (Playwright's sync API is not
thread-safe). The GUI talks to it through the `ui` object (log / step / stop / skip).
"""
import json
import os
import queue
import random
import re
import shutil
import sys
import time
from pathlib import Path

# pyrefly: ignore [missing-import]
from playwright.sync_api import sync_playwright
try:
    # pyrefly: ignore [missing-import]
    from playwright._impl._errors import TargetClosedError
except Exception:
    class TargetClosedError(Exception):
        pass

APP_DIR = Path(__file__).resolve().parent
SELECTORS_FILE = APP_DIR / "selectors.json"
LOGS_DIR = APP_DIR / "logs"
BATCH_STATE_FILE = APP_DIR / "batch_state.json"
POLICY_LOGS_FILE = LOGS_DIR / "policy_violations.json"
POLICY_LOGS_TXT = LOGS_DIR / "policy_violations.txt"

DEFAULTS = {
    "flow_url": "https://labs.google/fx/tools/flow",
    "project_url": "",            # optional: URL of the Flow project to work in
    "reload_each_pair": False,    # go back to project_url before every pair
    "profile_dir": "chrome_profile",
    "newest_tile": "first",       # which tile is the newest result: first | last
    "image_timeout": 120,         # seconds to wait for an image
    "video_timeout": 360,         # seconds to wait for a video
    "settle_image": 3,            # extra seconds after a new image tile appears
    "settle_video": 8,            # extra seconds after a new video tile appears
    "max_retries": 2,
    "delay_min": 1.0,             # random pause between actions (seconds)
    "delay_max": 3.0,
    "scripts_dir": "scripts",
    "move_script_when_done": True,
    "auto_advance_queue": True,   # automatically advance to next script when finished
    "script_file": "",
    "skip_image_gen": False,
    "resume_pair_index": 1,
    "show_browser_window": True,
    "pause_between_pairs": 5,
    "on_reject_action": "Ask me",
    "save_progress_auto": True,
    "videos_per_script": 8,
    "video_format": "9:16 vertical",
}

# key, instruction shown in the GUI, multi (matches many tiles)
STEPS = [
    ("image_prompt_box",
     "Click INSIDE the text box where you type the IMAGE prompt. "
     "It's usually a white area with placeholder text like 'Describe your image'.",
     False),
    ("image_generate",
     "Now click the GENERATE button (the button that starts image generation). "
     "Do NOT click Settings or any other button.",
     False),
    ("image_result",
     "⏳ WAIT for the image to finish generating. "
     "Then click on the GENERATED IMAGE TILE/THUMBNAIL itself (the picture, not any menu or button around it). "
     "This is CRITICAL — the script uses this to detect when new images appear.",
     True),
    ("project_more_options",
     "OPTIONAL (RECOMMENDED): Click the PROJECT's main 'More options' / three-dot button in the top toolbar. "
     "This tells the automation which button belongs to the project header so it will ALWAYS BE IGNORED. Otherwise press SKIP.",
     False),
    ("video_mode_menu",
     "Click the THREE-DOT button ('More options') specifically on the IMAGE TILE/CARD (hover over the image if needed to reveal it). "
     "Do NOT click the top project toolbar button.",
     False),
    ("video_mode",
     "Click the button/option that switches to VIDEO mode / 'Add to prompt' / 'Image to Video' / 'Animate'.",
     False),
    ("video_prompt_box",
     "Click INSIDE the VIDEO prompt text box (where you type the video/motion prompt).",
     False),
    ("video_generate",
     "Click the GENERATE button for the VIDEO (starts video generation). "
     "Do NOT click Settings or any other button.",
     False),
    ("video_result",
     "⏳ WAIT for the video to finish generating. "
     "Then click on the GENERATED VIDEO TILE/THUMBNAIL itself (the video preview, not any menu or button). "
     "This is CRITICAL — the script uses this to detect when new videos appear.",
     True),
]
MULTI_KEYS = {k for k, _, m in STEPS if m}

REQUIRED = [
    "image_prompt_box", "image_generate", "image_result",
    "video_mode_menu", "video_mode", "video_prompt_box", "video_generate",
    "video_result"
]

# Injected into every page during calibration. Reports the clicked element as a
# list of candidate selectors (best first). Includes an interactive pause/resume widget and Alt+P hotkey.
CAPTURE_JS = r"""
(() => {
  if (window.__flowInstalled) return;
  window.__flowInstalled = true;

  let isPaused = false;
  window.__flowSetPaused = (p) => {
    isPaused = !!p;
    updateWidget();
  };

  function updateWidget() {
    const w = document.getElementById('__flow_calib_widget');
    if (!w) return;
    if (isPaused) {
      w.innerHTML = '&#9654; <span style="color:#fbbf24">PAUSED</span> <span style="font-size:11px;opacity:0.8">(Click/Alt+P to Resume)</span>';
      w.style.borderColor = '#f59e0b';
      w.style.background = '#1c1917';
    } else {
      w.innerHTML = '&#10074;&#10074; <span style="color:#38bdf8">CALIBRATING</span> <span style="font-size:11px;opacity:0.8">(Click/Alt+P to Pause)</span>';
      w.style.borderColor = '#0284c7';
      w.style.background = '#0f172a';
    }
  }

  function ensureWidget() {
    if (document.getElementById('__flow_calib_widget')) return;
    const widget = document.createElement('div');
    widget.id = '__flow_calib_widget';
    widget.style.cssText = 'position:fixed;bottom:18px;right:20px;z-index:2147483647;padding:7px 14px;' +
      'background:#0f172a;color:#f8fafc;font-family:system-ui,-apple-system,sans-serif;font-size:13px;font-weight:600;' +
      'border-radius:24px;box-shadow:0 4px 16px rgba(0,0,0,0.4);cursor:pointer;user-select:none;' +
      'border:2px solid #0284c7;display:flex;align-items:center;gap:7px;transition:all 0.2s ease;';

    let isDragging = false, startX = 0, startY = 0, initLeft = 0, initTop = 0;
    widget.addEventListener('mousedown', (e) => {
      isDragging = false;
      startX = e.clientX;
      startY = e.clientY;
      const rect = widget.getBoundingClientRect();
      initLeft = rect.left;
      initTop = rect.top;
      function onMove(me) {
        if (Math.abs(me.clientX - startX) > 4 || Math.abs(me.clientY - startY) > 4) {
          isDragging = true;
          widget.style.right = 'auto';
          widget.style.bottom = 'auto';
          widget.style.left = (initLeft + (me.clientX - startX)) + 'px';
          widget.style.top = (initTop + (me.clientY - startY)) + 'px';
        }
      }
      function onUp() {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      }
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    });

    widget.addEventListener('click', (e) => {
      if (isDragging) return;
      e.stopPropagation();
      e.preventDefault();
      try {
        if (window.__flowReport) {
          Promise.resolve(window.__flowReport(JSON.stringify({action: 'toggle_pause'}))).catch(() => {});
        }
      } catch (_) {}
    }, true);

    if (document.body) {
      document.body.appendChild(widget);
    } else {
      document.addEventListener('DOMContentLoaded', () => document.body && document.body.appendChild(widget));
    }
    updateWidget();
  }
  ensureWidget();
  setInterval(ensureWidget, 2000);

  window.addEventListener('keydown', (e) => {
    if (e.altKey && (e.key === 'p' || e.key === 'P')) {
      e.preventDefault();
      e.stopPropagation();
      try {
        if (window.__flowReport) {
          Promise.resolve(window.__flowReport(JSON.stringify({action: 'toggle_pause'}))).catch(() => {});
        }
      } catch (_) {}
    }
  }, true);

  const q = (s) => String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const STATE_CLASS_REGEX = /(?:^|-)(?:focused|focus|active|hover|showing|backdrop-showing|selected|touched|dirty|invalid|pending|cdk-mouse-focused|cdk-program-focused|ProseMirror-focused)(?:$|-)/i;
  function candidates(el) {
    const t = el.closest('button,[role="button"],a,textarea,input,[contenteditable],img,video') || el;
    const tag = t.tagName.toLowerCase();
    const out = [];
    if (t.id && !/\d{4,}/.test(t.id)) out.push('#' + CSS.escape(t.id));
    const card = t.closest('flow-image-card, flow-media-card, flow-node, [class*="card"]');
    const cardTag = card ? card.tagName.toLowerCase() : '';
    const hasCardTag = cardTag && cardTag.startsWith('flow-');

    for (const a of ['data-testid', 'aria-label', 'placeholder', 'title', 'name']) {
      const v = t.getAttribute(a);
      if (v) {
        if (hasCardTag) out.push(cardTag + ' ' + tag + '[' + a + '="' + q(v) + '"]');
        out.push(tag + '[' + a + '="' + q(v) + '"]');
      }
    }
    const txt = (t.innerText || '').trim().replace(/\s+/g, ' ');
    if (txt && txt.length < 40 && (tag === 'button' || tag === 'a' || t.getAttribute('role') === 'button')) {
      const cleanTxt = txt.replace(/^[a-z0-9_]{2,15}\s+/i, '').trim();
      if (cleanTxt && cleanTxt !== txt && cleanTxt.length >= 3) {
        out.push(tag + ':has-text("' + q(cleanTxt) + '")');
      }
      out.push(tag + ':has-text("' + q(txt) + '")');
    }
    if (t.isContentEditable || tag === 'textarea' || t.classList.contains('ProseMirror')) {
      out.push('div.ProseMirror');
      out.push('div[contenteditable="true"]');
    }
    const cls = [...t.classList].filter(c => !/\d{3,}/.test(c) && !STATE_CLASS_REGEX.test(c)).slice(0, 3);
    if (cls.length) out.push(tag + '.' + cls.map(c => CSS.escape(c)).join('.'));
    const parts = [];
    let n = t, depth = 0;
    while (n && n.nodeType === 1 && n !== document.body && depth < 6) {
      let p = n.tagName.toLowerCase();
      const sibs = n.parentElement ? [...n.parentElement.children].filter(c => c.tagName === n.tagName) : [];
      if (sibs.length > 1) p += ':nth-of-type(' + (sibs.indexOf(n) + 1) + ')';
      parts.unshift(p);
      n = n.parentElement; depth++;
    }
    out.push(parts.join(' > '));
    return out;
  }
  document.addEventListener('click', (e) => {
    if (e.target && e.target.closest && e.target.closest('#__flow_calib_widget')) return;
    if (isPaused) return;
    try {
      if (window.__flowReport) {
        Promise.resolve(window.__flowReport(JSON.stringify(candidates(e.target)))).catch(() => {});
      }
    } catch (_) {}
  }, true);
})();
"""


class Stopped(Exception):
    pass


class PolicyViolationError(Exception):
    """Raised when Google Flow flags a prompt due to content or safety policy."""
    def __init__(self, message, stage="generation", prompt=""):
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.prompt = prompt


SCRIPT_STATES_DIR = LOGS_DIR / "script_states"


def get_script_state_file(script_path):
    """Returns the dedicated JSON state file path for a script."""
    SCRIPT_STATES_DIR.mkdir(parents=True, exist_ok=True)
    if not script_path:
        return SCRIPT_STATES_DIR / "custom_prompts_state.json"
    slug = re.sub(r'[^a-zA-Z0-9_\-]', '_', Path(script_path).stem)
    return SCRIPT_STATES_DIR / f"{slug}_state.json"


def load_script_state(script_path):
    """Loads persistent prompt-level execution state for a specific script."""
    sf = get_script_state_file(script_path)
    if sf.exists():
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Critical sanitization: A failed pair must NEVER be marked as completed
                failed_pairs = data.get("failed_pairs", [])
                failed_nums = {f.get("pair") for f in failed_pairs if isinstance(f, dict) and f.get("pair")}
                completed_pairs = data.get("completed_pairs", [])
                clean_completed = [c for c in completed_pairs if c not in failed_nums]
                if len(clean_completed) != len(completed_pairs):
                    data["completed_pairs"] = clean_completed
                    try:
                        sf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                return data
        except Exception:
            pass
    return None


def save_script_state(script_path, state):
    """Saves persistent prompt-level execution state for a specific script."""
    try:
        sf = get_script_state_file(script_path)
        sf.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(state, dict):
            failed_nums = {f.get("pair") for f in state.get("failed_pairs", []) if isinstance(f, dict) and f.get("pair")}
            if failed_nums and "completed_pairs" in state:
                state["completed_pairs"] = [c for c in state["completed_pairs"] if c not in failed_nums]
        sf.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def clear_script_state(script_path):
    """Deletes persistent prompt-level execution state for a specific script."""
    try:
        sf = get_script_state_file(script_path)
        if sf.exists():
            sf.unlink()
    except Exception:
        pass


def load_batch_state():
    """Load persistent execution state from batch_state.json."""
    if BATCH_STATE_FILE.exists():
        try:
            data = json.loads(BATCH_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                failed_pairs = data.get("failed_pairs", [])
                failed_nums = {f.get("pair") for f in failed_pairs if isinstance(f, dict) and f.get("pair")}
                completed_pairs = data.get("completed_pairs", [])
                clean_completed = [c for c in completed_pairs if c not in failed_nums]
                if len(clean_completed) != len(completed_pairs):
                    data["completed_pairs"] = clean_completed
                    try:
                        BATCH_STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                return data
        except Exception:
            pass
    return None


def save_batch_state(state):
    """Save persistent execution state to batch_state.json."""
    try:
        if isinstance(state, dict):
            failed_nums = {f.get("pair") for f in state.get("failed_pairs", []) if isinstance(f, dict) and f.get("pair")}
            if failed_nums and "completed_pairs" in state:
                state["completed_pairs"] = [c for c in state["completed_pairs"] if c not in failed_nums]
        BATCH_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def clear_batch_state():
    """Clear or delete batch_state.json."""
    try:
        if BATCH_STATE_FILE.exists():
            BATCH_STATE_FILE.unlink()
    except Exception:
        pass


def detect_policy_violation(page):
    """Inspects the page strictly for active Google Flow safety/policy violation snackbars.
    Returns:
        dict: {"detected": bool, "message": str}
    """
    try:
        res = page.evaluate(r"""() => {
            const strictPolicyKeywords = [
                'content policy', 'safety policy', 'safety guideline',
                'violates our safety', 'violates our content', 'violate our safety', 'violate our content',
                'policy violation', 'flagged for moderation', 'prompt was declined',
                'prohibited by safety', 'cannot generate this prompt'
            ];

            // Only check genuine active floating toasts or snackbars (NOT cards, NOT dialogs, NOT canvas)
            const alertEls = Array.from(document.querySelectorAll(
                'mat-snack-bar-container, .mat-mdc-snack-bar-container, flow-toast, flow-error-banner'
            ));

            for (const el of alertEls) {
                if (!el || el.offsetParent === null) continue;
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

                const text = (el.innerText || el.textContent || '').trim();
                if (!text) continue;
                const lower = text.toLowerCase();
                for (const kw of strictPolicyKeywords) {
                    if (lower.includes(kw)) {
                        return { detected: true, message: text.slice(0, 300) };
                    }
                }
            }

            return { detected: false, message: '' };
        }""")
        return res if res else {"detected": False, "message": ""}
    except Exception:
        return {"detected": False, "message": ""}


def record_policy_violation(script_name, pair_index, img_prompt, vid_prompt, reason, stage, output_dir=""):
    """Records a policy violation to both JSON and text log files."""
    import datetime
    timestamp = datetime.datetime.now().isoformat()
    record = {
        "timestamp": timestamp,
        "script_name": script_name,
        "pair_index": pair_index,
        "stage": stage,
        "reason": reason,
        "image_prompt": img_prompt,
        "video_prompt": vid_prompt,
    }

    # 1. Global JSON log
    LOGS_DIR.mkdir(exist_ok=True)
    all_violations = []
    if POLICY_LOGS_FILE.exists():
        try:
            all_violations = json.loads(POLICY_LOGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            all_violations = []
    all_violations.append(record)
    try:
        POLICY_LOGS_FILE.write_text(json.dumps(all_violations, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    # 2. Global human-readable text log
    txt_entry = (
        f"[{timestamp}] ⚠️ POLICY VIOLATION DETECTED\n"
        f"Script: {script_name} | Pair #{pair_index} | Stage: {stage}\n"
        f"Reason: {reason}\n"
        f"Image Prompt: {img_prompt}\n"
        f"Video Prompt: {vid_prompt}\n"
        f"{'-'*80}\n"
    )
    try:
        with open(POLICY_LOGS_TXT, "a", encoding="utf-8") as f:
            f.write(txt_entry)
    except Exception:
        pass

    # 3. Output directory log (if output folder specified)
    if output_dir:
        out_p = Path(output_dir)
        try:
            out_p.mkdir(parents=True, exist_ok=True)
            out_json = out_p / "policy_violations.json"
            out_txt = out_p / "policy_violations.txt"
            script_violations = []
            if out_json.exists():
                try:
                    script_violations = json.loads(out_json.read_text(encoding="utf-8"))
                except Exception:
                    script_violations = []
            script_violations.append(record)
            out_json.write_text(json.dumps(script_violations, indent=2, ensure_ascii=False), encoding="utf-8")
            with open(out_txt, "a", encoding="utf-8") as f:
                f.write(txt_entry)
        except Exception:
            pass


# ----------------------------------------------------------------- helpers
def load_selectors():
    if SELECTORS_FILE.exists():
        return json.loads(SELECTORS_FILE.read_text(encoding="utf-8"))
    return {}


def save_selectors(sels):
    SELECTORS_FILE.write_text(json.dumps(sels, indent=2, ensure_ascii=False), encoding="utf-8")


def abs_path(p):
    p = Path(p)
    return p if p.is_absolute() else APP_DIR / p


def clean_selector(sel):
    """Strip transient CSS state classes (focus, active, etc.) that only exist while focused."""
    if not sel:
        return sel
    for transient in [
        ".ProseMirror-focused",
        ".cdk-focused",
        ".mat-focused",
        ".cdk-program-focused",
        ".cdk-mouse-focused",
    ]:
        sel = sel.replace(transient, "")
    return sel.strip()


DOM_MONITOR_JS = r"""
(() => {
  if (window.__flowDomObserverInstalled) return;
  window.__flowDomObserverInstalled = true;

  function getElementSummary(el) {
    if (!el || el.nodeType !== 1) return '';
    const tag = el.tagName.toLowerCase();
    const cls = el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    const id = el.id ? '#' + el.id : '';
    const aria = el.getAttribute('aria-label') ? '[aria="' + el.getAttribute('aria-label') + '"]' : '';
    return tag + id + cls + aria;
  }

  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === 'childList') {
        for (const node of m.addedNodes) {
          if (node.nodeType === 1) {
            const sum = getElementSummary(node);
            if (sum.includes('tile') || sum.includes('progress') || sum.includes('video') || sum.includes('card') || sum.includes('image') || sum.includes('icon')) {
              try {
                if (window.__flowDomLog) {
                  Promise.resolve(window.__flowDomLog(JSON.stringify({type: 'added', el: sum, parent: getElementSummary(m.target)}))).catch(() => {});
                }
              } catch (_) {}
            }
          }
        }
        for (const node of m.removedNodes) {
          if (node.nodeType === 1) {
            const sum = getElementSummary(node);
            if (sum.includes('progress') || sum.includes('bar') || sum.includes('spinner') || sum.includes('loading')) {
              try {
                if (window.__flowDomLog) {
                  Promise.resolve(window.__flowDomLog(JSON.stringify({type: 'removed', el: sum, parent: getElementSummary(m.target)}))).catch(() => {});
                }
              } catch (_) {}
            }
          }
        }
      } else if (m.type === 'attributes') {
        if (m.attributeName === 'class' || m.attributeName === 'aria-busy') {
          const sum = getElementSummary(m.target);
          if (sum.includes('tile') || sum.includes('card') || sum.includes('progress') || sum.includes('video')) {
            try {
              if (window.__flowDomLog) {
                Promise.resolve(window.__flowDomLog(JSON.stringify({type: 'attr', name: m.attributeName, el: sum, val: m.target.getAttribute(m.attributeName)}))).catch(() => {});
              }
            } catch (_) {}
          }
        }
      }
    }
  });

  window.addEventListener('beforeunload', () => {
    try { observer.disconnect(); } catch (_) {}
  });
  window.addEventListener('pagehide', () => {
    try { observer.disconnect(); } catch (_) {}
  });

  function startObserving() {
    if (!document.body) {
      setTimeout(startObserving, 500);
      return;
    }
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'aria-busy', 'aria-valuenow', 'hidden', 'disabled']
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startObserving);
  } else {
    startObserving();
  }
})();
"""


def setup_dom_logging(ctx, ui):
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        dom_events_file = LOGS_DIR / "dom_events.log"
        with open(dom_events_file, "a", encoding="utf-8") as f:
            f.write(f"\n--- SESSION STARTED {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")

        def on_dom_log(raw_json):
            try:
                evt = json.loads(raw_json)
                ts = time.strftime("%H:%M:%S")
                evt_type = evt.get("type", "event")
                msg = f"[{ts}] [{evt_type.upper()}] {evt.get('el', '')}"
                if evt.get("parent"):
                    msg += f" in {evt['parent']}"
                if evt.get("name"):
                    msg += f" ({evt['name']}='{evt.get('val', '')}')"
                with open(dom_events_file, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass

        ctx.expose_function("__flowDomLog", on_dom_log)
        ctx.add_init_script(DOM_MONITOR_JS)
    except Exception as e:
        ui.log(f"   [DOM Logger notice]: {e}")


def launch(pw, cfg, ui):
    profile_dir = abs_path(cfg.get("profile_dir", "chrome_profile"))
    profile_dir.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    downloads_dir = abs_path(cfg.get("output_dir", "output")) / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    extra_args = [
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-features=IsolateOrigins,site-per-process",
    ]
    kwargs = dict(
        user_data_dir=str(profile_dir),
        headless=not cfg.get("show_browser_window", True),
        accept_downloads=True,
        downloads_path=str(downloads_dir),
        no_viewport=True,
        ignore_default_args=["--enable-automation"],
        args=extra_args,
    )
    ui.log(f"Launching Playwright Chromium (profile: {profile_dir.name})...")
    ctx = pw.chromium.launch_persistent_context(**kwargs)
    setup_dom_logging(ctx, ui)
    return ctx


def check_stop(ui):
    if ui.stop.is_set():
        raise Stopped()


def pause(cfg, ui):
    check_stop(ui)
    dmin = max(3.0, float(cfg.get("delay_min", 3.0)))
    dmax = max(dmin, float(cfg.get("delay_max", 3.0)))
    time.sleep(random.uniform(dmin, dmax))


def count(page, sel):
    try:
        return page.locator(clean_selector(sel)).count()
    except Exception:
        return 0


def highlight_element(page, target, color="#ef4444", duration_ms=2500):
    """Draw a glowing, high-visibility colored outline around the target element."""
    try:
        if isinstance(target, str):
            csel = clean_selector(target)
            loc = page.locator(csel).first
        else:
            loc = target
        if loc.count() > 0:
            loc.evaluate(f"""(el) => {{
                try {{
                    const oldOutline = el.style.outline;
                    const oldBoxShadow = el.style.boxShadow;
                    const oldZIndex = el.style.zIndex;
                    const oldTransition = el.style.transition;
                    el.style.outline = '4px solid {color}';
                    el.style.boxShadow = '0 0 25px 8px {color}';
                    el.style.zIndex = '2147483647';
                    el.style.transition = 'all 0.15s ease';
                    setTimeout(() => {{
                        try {{
                            el.style.outline = oldOutline;
                            el.style.boxShadow = oldBoxShadow;
                            el.style.zIndex = oldZIndex;
                            el.style.transition = oldTransition;
                        }} catch (_) {{}}
                    }}, {duration_ms});
                }} catch (_) {{}}
            }}""")
    except Exception:
        pass


def click(page, sel, timeout=30000, force=False):
    """Click an element identified by selector, with red glow highlight and 3s delay."""
    csel = clean_selector(sel)
    loc = page.locator(csel).first
    loc.wait_for(state="attached", timeout=timeout)
    highlight_element(page, loc, color="#ef4444", duration_ms=3000)
    page.wait_for_timeout(1000)  # 1s pre-click delay so user can visually see what is targeted
    loc.click(timeout=timeout, force=force)
    page.wait_for_timeout(3000)  # 3s post-click delay


def click_loc(page, loc, timeout=30000, force=False):
    """Click a locator object directly, with red glow highlight and 3s delay."""
    loc.wait_for(state="attached", timeout=timeout)
    highlight_element(page, loc, color="#ef4444", duration_ms=3000)
    page.wait_for_timeout(1000)  # 1s pre-click delay so user can visually see what is targeted
    loc.click(timeout=timeout, force=force)
    page.wait_for_timeout(3000)  # 3s post-click delay


def wait_visible(page, sel, timeout_s):
    csel = clean_selector(sel)
    page.locator(csel).first.wait_for(state="visible", timeout=timeout_s * 1000)


def fill(page, sel, text):
    csel = clean_selector(sel)
    loc = page.locator(csel).first
    loc.wait_for(state="attached", timeout=30000)
    highlight_element(page, loc, color="#38bdf8", duration_ms=2500)
    page.wait_for_timeout(1000)
    loc.click()
    page.wait_for_timeout(500)
    try:
        loc.fill(text)
    except Exception:
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.keyboard.insert_text(text)
    page.wait_for_timeout(3000)  # 3s delay after typing prompt


def pick(page, sel, cfg):
    loc = page.locator(clean_selector(sel))
    return loc.first if cfg.get("newest_tile", "first") == "first" else loc.last


def is_generation_in_progress(page):
    """Check if Google Flow is actively generating an image or video."""
    try:
        return page.evaluate("""() => {
            function isActivelyVisible(elem) {
                if (!elem) return false;
                const style = window.getComputedStyle(elem);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const r = elem.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            }
            const selectors = [
                'mat-progress-bar', 'mat-spinner', '[role="progressbar"]',
                '.mat-mdc-progress-bar', 'flow-media-progress',
                '.loading-spinner', '.progress-bar', '.mat-progress-spinner'
            ];
            for (const s of selectors) {
                const els = document.querySelectorAll(s);
                for (const el of els) {
                    if (isActivelyVisible(el)) {
                        return true;
                    }
                }
            }
            return false;
        }""")
    except Exception:
        return False


def get_tile_srcs(page, sel):
    """Retrieve all current image/video src URLs for the specified selector."""
    try:
        csel = clean_selector(sel)
        return page.evaluate("""(sel) => {
            return Array.from(document.querySelectorAll(sel))
                .map(el => el.currentSrc || el.src || '')
                .filter(s => s && !s.startsWith('data:image/svg'));
        }""", csel)
    except Exception:
        return []


def pick_target_tile(page, sel, before_srcs, cfg):
    """Pick the target tile: strictly prioritizes the newly generated tile (whose src was not in before_srcs),
    falling back to newest_tile setting ('first' or 'last')."""
    csel = clean_selector(sel)
    try:
        loc = page.locator(csel)
        cnt = loc.count()
        if cnt == 0:
            return loc.first
        if before_srcs:
            for idx in range(cnt):
                el_loc = loc.nth(idx)
                src = el_loc.evaluate("(el) => el.currentSrc || el.src || ''")
                if src and src not in before_srcs and not src.startswith("data:image/svg"):
                    return el_loc
    except Exception:
        pass
    return pick(page, sel, cfg)


def inspect_and_log_dom(page, sel, before_srcs, cfg, label, elapsed, timeout_s, ui):
    """Deep DOM inspection of the target tile and live logging to logs/dom_debug.log and ui.
    Strictly isolates the newly generated tile and prevents any selection of prior/old tiles."""
    try:
        csel = clean_selector(sel)
        newest = cfg.get("newest_tile", "first")
        res = page.evaluate(r"""({sel, newest, label, before_srcs_list}) => {
            const beforeSet = new Set(before_srcs_list || []);
            const thumbnails = Array.from(document.querySelectorAll(sel));

            function isActivelyVisible(elem) {
                if (!elem) return false;
                if (elem.closest('.fading-out')) return false;
                const style = window.getComputedStyle(elem);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const r = elem.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            }

            // 1. Detect active generation on the canvas (Google Flow's native pending states strictly)
            const pendingEls = Array.from(document.querySelectorAll(
                'flow-pending-tile:not(.fading-out), .loading-percentage, [class*="loading-percentage"], flow-media-progress'
            ));
            const activePending = [];
            let currentPct = null;

            for (const p of pendingEls) {
                if (isActivelyVisible(p)) {
                    const tag = p.tagName.toLowerCase();
                    const cls = p.className && typeof p.className === 'string' ? '.' + p.className.split(' ')[0] : '';
                    const fullTxt = (p.innerText || p.textContent || '').trim();
                    const txtSnip = fullTxt.replace(/\s+/g, ' ').slice(0, 40);
                    activePending.push(`${tag}${cls}${txtSnip ? '[' + txtSnip + ']' : ''}`);

                    // Look for live percentage (e.g. 0%, 5%, 38%, 100%)
                    const pm = fullTxt.match(/\b(\d{1,3})\s*%/);
                    if (pm) {
                        const val = parseInt(pm[1], 10);
                        if (!isNaN(val) && val >= 0 && val <= 100) {
                            if (currentPct === null || val > currentPct) {
                                currentPct = val;
                            }
                        }
                    }
                }
            }

            // Also check progress bar aria-valuenow if available
            if (currentPct === null) {
                const progBars = Array.from(document.querySelectorAll('mat-progress-bar, [role="progressbar"], .mat-mdc-progress-bar'));
                for (const pb of progBars) {
                    if (isActivelyVisible(pb)) {
                        const v = pb.getAttribute('aria-valuenow');
                        if (v !== null && v !== '') {
                            const val = parseInt(v, 10);
                            if (!isNaN(val) && val >= 0 && val <= 100) {
                                currentPct = val;
                                break;
                            }
                        }
                    }
                }
            }

            const canvasGenerating = activePending.length > 0 || (currentPct !== null && currentPct < 100);

            // 2. Identify the NEW tile specifically:
            // A thumbnail whose src is genuinely new (not in beforeSet)
            let targetCard = null;
            let targetThumb = null;
            let isNewSrc = false;

            for (const thumb of thumbnails) {
                const s = thumb.currentSrc || thumb.src || '';
                if (s && !beforeSet.has(s) && !s.startsWith('data:image/svg')) {
                    targetThumb = thumb;
                    targetCard = thumb.closest('flow-video-tile, flow-grid-tile-container, flow-tile-container, flow-node, [class*="card"]') || thumb.parentElement;
                    isNewSrc = true;
                    break;
                }
            }

            // CRITICAL SAFEGUARD: If existing videos exist from prior runs, and no new thumbnail
            // src has appeared yet, the new video is STILL GENERATING.
            // NEVER fall back to thumbnails[0] (which is an old completed video)!
            if (beforeSet.size > 0 && !targetThumb) {
                return {
                    found_card: false,
                    is_new_src: false,
                    canvas_generating: canvasGenerating,
                    percentage: currentPct,
                    visible_progress: activePending,
                    cards_count: thumbnails.length,
                    ready: false,
                    status_note: 'waiting_for_new_tile'
                };
            }

            // If beforeSet was empty (fresh project with 0 existing tiles), use newest setting
            if (!targetThumb) {
                if (thumbnails.length > 0) {
                    targetThumb = newest === 'first' ? thumbnails[0] : thumbnails[thumbnails.length - 1];
                    targetCard = targetThumb.closest('flow-video-tile, flow-grid-tile-container, flow-tile-container, flow-node, [class*="card"]') || targetThumb.parentElement;
                }
            }

            if (!targetCard) {
                return {
                    found_card: false,
                    is_new_src: false,
                    canvas_generating: canvasGenerating,
                    percentage: currentPct,
                    visible_progress: activePending,
                    ready: false
                };
            }

            // 3. Inspect target card in detail
            const cardTag = targetCard.tagName.toLowerCase();
            const cardClass = (targetCard.className && typeof targetCard.className === 'string') ? targetCard.className.trim().slice(0, 60) : '';

            // Card-scoped progress bars
            const progressBars = Array.from(targetCard.querySelectorAll('mat-progress-bar, [role="progressbar"], .mat-mdc-progress-bar, mat-spinner, flow-media-progress, .loading-percentage'));
            const cardProgress = [];
            for (const pb of progressBars) {
                if (isActivelyVisible(pb)) {
                    cardProgress.push(pb.tagName.toLowerCase());
                }
            }

            // Card text
            const rawText = (targetCard.innerText || '').trim();
            const genMatch = rawText.match(/(?:generating|rendering|creating|processing|upscaling|waiting in the queue|\b\d+%\b)/i);
            const genText = genMatch ? genMatch[0] : '';
            if (currentPct === null && rawText) {
                const cm = rawText.match(/\b(\d{1,3})\s*%/);
                if (cm) {
                    const val = parseInt(cm[1], 10);
                    if (!isNaN(val) && val >= 0 && val <= 100) {
                        currentPct = val;
                    }
                }
            }

            // Thumbnail state
            const thumbImg = targetThumb || targetCard.querySelector('img');
            const thumbLoaded = !!(thumbImg && thumbImg.complete && thumbImg.naturalWidth > 50);
            const thumbDims = thumbImg ? `${thumbImg.naturalWidth}x${thumbImg.naturalHeight}` : 'none';

            // Play indicator on the target card
            let playIndicator = null;
            const icons = Array.from(targetCard.querySelectorAll('mat-icon, flow-icon, i, span, div, button'));
            for (const ic of icons) {
                const t = (ic.textContent || '').trim().toLowerCase();
                if (t === 'play_arrow' || t === 'play' || t === 'play_circle') {
                    playIndicator = `icon:${t}`;
                    break;
                }
                const al = (ic.getAttribute('aria-label') || '').toLowerCase();
                if (al.includes('play') && !al.includes('display')) {
                    playIndicator = `aria:${al}`;
                    break;
                }
            }

            if (!playIndicator) {
                const playBtn = targetCard.querySelector('button[aria-label*="Play" i], [class*="play-button" i], [class*="play-icon-badge" i], [class*="play-badge" i]');
                if (playBtn && isActivelyVisible(playBtn)) {
                    playIndicator = 'button:play';
                }
            }

            if (!playIndicator) {
                const vid = targetCard.querySelector('video') || document.querySelector('flow-video-player video, .video-player video');
                if (vid && (vid.currentSrc || vid.src)) {
                    playIndicator = 'video_tag_active';
                }
            }

            const isPreviewOpen = !!document.querySelector('.editor-container, flow-editor, flow-video-player, flow-media-viewer');
            if (isPreviewOpen) {
                playIndicator = playIndicator || 'preview_modal_open';
            }

            // Video readiness condition:
            // 1. Must be genuinely new src (if beforeSet has items)
            // 2. ABSOLUTELY NO active pending generation on canvas (!canvasGenerating && activePending.length === 0)
            // 3. Percentage must NOT be < 100 (if percentage is detected, it must have reached 100% or finished)
            // 4. Target card must not be a flow-pending-tile
            // 5. Card-level progress bars must be 0
            // 6. No generating / percentage text on card
            // 7. Video thumbnail loaded with proper dimensions
            // 8. Play indicator verified (play_circle badge, play button, or preview open)
            let isReady = false;
            const newOrInitial = beforeSet.size > 0 ? isNewSrc : true;
            const notPending = !canvasGenerating && activePending.length === 0;
            const pctOk = (currentPct === null || currentPct >= 100);
            const notPendingTile = cardTag !== 'flow-pending-tile';

            if (label === 'image') {
                isReady = notPending && pctOk && notPendingTile && newOrInitial && cardProgress.length === 0 && !genText && thumbLoaded;
            } else {
                const isHighRes = !!(thumbImg && (thumbImg.naturalWidth >= 400 || thumbImg.naturalHeight >= 600 || thumbImg.naturalWidth > 288));
                isReady = notPending && pctOk && notPendingTile && newOrInitial && cardProgress.length === 0 && !genText && thumbLoaded && (isHighRes || !!playIndicator);
            }

            return {
                found_card: true,
                card_tag: cardTag,
                card_class: cardClass,
                is_new_src: isNewSrc,
                canvas_generating: canvasGenerating,
                percentage: currentPct,
                visible_progress: activePending.length > 0 ? activePending : cardProgress,
                thumb_loaded: thumbLoaded,
                thumb_dims: thumbDims,
                gen_text: genText,
                play_indicator: playIndicator,
                is_preview_open: isPreviewOpen,
                ready: isReady
            };
        }""", {
            "sel": csel,
            "newest": newest,
            "label": label,
            "before_srcs_list": list(before_srcs or [])
        })

        # Append structured entry to logs/dom_debug.log
        dom_debug_file = LOGS_DIR / "dom_debug.log"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        pct_display = f"{res.get('percentage')}%" if res.get('percentage') is not None else "None"
        log_entry = (
            f"[{ts}] [{label.upper()} @ {elapsed}s/{timeout_s}s]\n"
            f"  found_card: {res.get('found_card')} (<{res.get('card_tag')}> class='{res.get('card_class')}')\n"
            f"  new_src: {res.get('is_new_src')}, canvas_generating: {res.get('canvas_generating')}, dims: {res.get('thumb_dims')}, loaded: {res.get('thumb_loaded')}\n"
            f"  percentage: {pct_display}, pending_progress: {res.get('visible_progress')}, text: '{res.get('gen_text')}'\n"
            f"  play_indicator: {res.get('play_indicator')}, preview_open: {res.get('is_preview_open')}\n"
            f"  => READY: {res.get('ready')}\n\n"
        )
        try:
            with open(dom_debug_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception:
            pass

        return bool(res.get("ready")), res
    except Exception as ex:
        return False, {"error": str(ex)}


def is_tile_ready(page, sel, cfg, label="image"):
    """Backward-compatible boolean wrapper."""
    ready, _ = inspect_and_log_dom(page, sel, [], cfg, label, 0, 0, None)
    return ready


def wait_new(page, sel, before_count, before_srcs, timeout_s, ui, label, prompt="", pair_index=None):
    csel = clean_selector(sel)
    ui.log(f"   waiting for {label} (timeout={timeout_s}s)...")
    ui.log(f"   watching selector: {csel}  (count before={before_count})")
    start = time.time()
    end = start + timeout_s
    last_report = start
    last_pct = None
    last_pct_time = 0
    tile_appeared = False
    cfg = getattr(ui, "cfg", {})
    is_test = bool(cfg.get("test_mode", False))
    min_video_time = 15 if (label == "video" and not is_test) else 0

    while time.time() < end:
        check_stop(ui)

        now_count = count(page, sel)
        elapsed = int(time.time() - start)

        current_srcs = get_tile_srcs(page, sel)
        new_srcs = [s for s in current_srcs if before_srcs and s not in before_srcs]

        # Strictly wait for a new tile or new src
        if now_count > before_count or len(new_srcs) > 0:
            tile_appeared = True

        # Deep DOM inspection and logging
        ready, diag = inspect_and_log_dom(page, sel, before_srcs, cfg, label, elapsed, timeout_s, ui)

        # Track and announce live generation percentage (e.g. 0%, 5%, 38%, 100%)
        pct = diag.get("percentage")
        if pct is not None:
            now = time.time()
            if pct != last_pct or (now - last_pct_time >= 8):
                last_pct = pct
                last_pct_time = now
                ui.log(f"   ... {label} progress: {pct}% ({elapsed}s elapsed)")
                if hasattr(ui, "step"):
                    ui.step(f"Generating {label}: {pct}% ({elapsed}s)", False)
                if pair_index and hasattr(ui, "pair_stage"):
                    ui.pair_stage(pair_index, label, f"work:{pct}%")

        # Ready triggered when genuine new tile completed
        if tile_appeared and ready:
            if label == "video":
                # Strict video generation guards: NEVER conclude while canvas is still generating
                if diag.get("canvas_generating"):
                    pass  # Still actively generating on canvas
                elif diag.get("percentage") is not None and diag.get("percentage") < 100:
                    pass  # Still counting up to 100%
                elif elapsed < min_video_time:
                    pass  # Transient DOM artifact during initial node setup
                else:
                    ui.log(f"   ✓ {label} completed! (count {before_count}→{now_count}, took {elapsed}s)")
                    if pair_index and hasattr(ui, "pair_stage"):
                        ui.pair_stage(pair_index, label, "ok")
                    return
            else:
                ui.log(f"   ✓ {label} completed! (count {before_count}→{now_count}, took {elapsed}s)")
                if pair_index and hasattr(ui, "pair_stage"):
                    ui.pair_stage(pair_index, label, "ok")
                return

        # Direct card verification: thumbnail loaded with dimensions, and STRICTLY no active canvas generation
        if (tile_appeared and diag.get("thumb_loaded") and not diag.get("canvas_generating")
                and len(diag.get("visible_progress", [])) == 0 and not diag.get("gen_text")):
            pct_val = diag.get("percentage")
            if pct_val is None or pct_val >= 100:
                if label == "image":
                    ui.log(f"   ✓ {label} completed! (thumbnail verified {diag.get('thumb_dims')}, took {elapsed}s)")
                    if pair_index and hasattr(ui, "pair_stage"):
                        ui.pair_stage(pair_index, label, "ok")
                    return
                elif diag.get("play_indicator") and elapsed >= min_video_time:
                    ui.log(f"   ✓ {label} completed! (thumbnail verified {diag.get('thumb_dims')}, play indicator {diag.get('play_indicator')}, took {elapsed}s)")
                    if pair_index and hasattr(ui, "pair_stage"):
                        ui.pair_stage(pair_index, label, "ok")
                    return

        # Policy & Safety Violation Check: ONLY if NO tile has appeared after at least 6s of waiting
        if not tile_appeared and elapsed >= 6:
            pol = detect_policy_violation(page)
            if pol.get("detected"):
                msg = pol.get("message") or f"Policy violation detected during {label} generation"
                ui.log(f"   ⚠️ [POLICY VIOLATION DETECTED] {msg}")
                raise PolicyViolationError(msg, stage=label, prompt=prompt)

        # Progress report every 10 seconds with live DOM diagnostics
        now = time.time()
        if now - last_report >= 10:
            status = "rendering content..." if tile_appeared else "waiting for new tile..."
            if label == "video" and diag:
                pct_str = f"pct={diag.get('percentage')}%" if diag.get('percentage') is not None else ""
                pb_list = diag.get("visible_progress", [])
                pb_str = f"progress={pb_list}" if pb_list else "progress=[]"
                new_str = f"new_src={diag.get('is_new_src', False)}"
                play_str = f"play={diag.get('play_indicator') or False}"
                dims_str = f"thumb={diag.get('thumb_dims', '')}"
                diag_items = [p for p in [pct_str, pb_str, new_str, play_str, dims_str] if p]
                diag_str = " | " + ", ".join(diag_items) if diag_items else ""
                ui.log(f"   ... still waiting for {label} ({elapsed}s / {timeout_s}s elapsed, {status}{diag_str})")
            else:
                ui.log(f"   ... still waiting for {label} ({elapsed}s / {timeout_s}s elapsed, {status})")
            last_report = now

        page.wait_for_timeout(2000)

    current_srcs = get_tile_srcs(page, sel)
    new_srcs = [s for s in current_srcs if before_srcs and s not in before_srcs]
    if tile_appeared or (now_count > before_count) or (len(new_srcs) > 0):
        elapsed = int(time.time() - start)
        ui.log(f"   ⚠ {label} reached timeout ({timeout_s}s), proceeding with detected tile...")
        if pair_index and hasattr(ui, "pair_stage"):
            ui.pair_stage(pair_index, label, "ok")
        return

    raise TimeoutError(
        f"Timed out waiting for {label} after {timeout_s}s. "
        f"Selector '{csel}' had count={now_count} (expected >{before_count}). "
        f"You may need to re-calibrate this step."
    )


def is_project_header_element(loc, sels):
    """Check whether an element is inside the top project header / toolbar or matches project_more_options."""
    try:
        is_hdr = loc.evaluate("""(el) => {
            if (el.closest('flow-more-options-menu, header, mat-toolbar, flow-project-header, [class*="toolbar"], [class*="project-header"]')) {
                return true;
            }
            const r = el.getBoundingClientRect();
            // Google Flow's top project toolbar is fixed in the top ~75px
            if (r.top >= 0 && r.bottom <= 75) {
                return true;
            }
            return false;
        }""")
        if is_hdr:
            return True
    except Exception:
        pass
    proj_sel = sels.get("project_more_options")
    if proj_sel:
        try:
            if loc.evaluate("(el, sel) => el.matches(sel) || !!el.closest('flow-more-options-menu')", clean_selector(proj_sel)):
                return True
        except Exception:
            pass
    return False


def close_image_viewer(page, sels, ui, n=1):
    """Close the image editor / viewer modal and return to canvas."""
    ui.log(f"[{n}] returning to main canvas / menu...")
    page.wait_for_timeout(2000)

    # 1. Try calibrated selector
    if sels.get("image_back_to_menu"):
        try:
            b = page.locator(clean_selector(sels["image_back_to_menu"])).first
            if b.count() > 0 and b.is_visible():
                b.click(timeout=4000)
                page.wait_for_timeout(2000)
                ui.log(f"[{n}] clicked image_back_to_menu")
        except Exception as e:
            ui.log(f"   image_back_to_menu selector notice: {e}")

    def is_editor_open():
        try:
            return page.evaluate("""() => {
                const ed = document.querySelector('.editor-container, flow-editor, [class*="editor-container"]');
                return ed && (ed.offsetParent !== null || ed.getClientRects().length > 0);
            }""")
        except Exception:
            return False

    # 2. Try common back/close buttons if editor is still open
    if is_editor_open():
        for sel in [
            'button[aria-label*="Back" i]',
            'button[aria-label*="close" i]',
            'button[aria-label*="Finished" i]',
            'button:has-text("arrow_back")',
            'button:has-text("close")',
            '.editor-container button',
        ]:
            try:
                b = page.locator(sel).first
                if b.count() > 0 and b.is_visible():
                    ui.log(f"   closing editor via fallback button: {sel}")
                    b.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    if not is_editor_open():
                        break
            except Exception:
                pass

    # 3. Fallback: Escape key
    if is_editor_open():
        ui.log(f"   editor overlay still detected, pressing Escape key to return to canvas...")
        page.keyboard.press("Escape")
        page.wait_for_timeout(2000)
        if is_editor_open():
            page.keyboard.press("Escape")
            page.wait_for_timeout(2000)

    if not is_editor_open():
        ui.log(f"[{n}] successfully returned to canvas.")
    else:
        ui.log(f"[{n}] ⚠ Note: editor overlay may still be present. Use Single-Step Recalibration on 'image_back_to_menu' if needed.")

    page.wait_for_timeout(2000)


def open_image_context_menu(page, tile, sels, cfg, ui, n=1):
    """Open the context / more options menu specifically for the target image card.
    Strictly ignores the main project toolbar's 'More options' button.
    Crucially: NEVER clicks the image tile directly (which opens the image viewer modal),
    only hovers to reveal the floating hotbar and clicks its 3-dots button."""
    # 1. Dismiss any lingering viewer/editor modal
    try:
        is_ed = page.evaluate("""() => {
            const ed = document.querySelector('.editor-container, flow-editor, [class*="editor-container"]');
            return ed && (ed.offsetParent !== null || ed.getClientRects().length > 0);
        }""")
        if is_ed:
            ui.log(f"[{n}] dismissing editor modal via Escape...")
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)
    except Exception:
        pass

    ui.log(f"[{n}] hovering image tile to reveal card options hotbar...")

    # Hover the image tile (NEVER CLICK THE IMAGE TILE)
    try:
        highlight_element(page, tile, color="#38bdf8", duration_ms=2000)
        tile.hover(force=True, timeout=4000)
        page.wait_for_timeout(1000)
    except Exception as e:
        ui.log(f"   tile hover notice: {e}")

    # Also hover the card / tile container ancestor and dispatch mouse events
    container = None
    try:
        container = tile.locator("xpath=./ancestor::flow-tile-container | ./ancestor::flow-image-tile | ./ancestor::flow-grid-tile-container | ./ancestor::flow-media-card | ./ancestor::flow-image-card | ./ancestor::flow-node").first
        if container.count() > 0:
            container.hover(force=True, timeout=3000)
            page.wait_for_timeout(1000)
        tile.evaluate("""(el) => {
            el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
            el.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            const c = el.closest('flow-tile-container, flow-image-tile, flow-grid-tile-container, flow-image-card, flow-media-card, flow-node');
            if (c) {
                c.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                c.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            }
        }""")
    except Exception:
        pass

    page.wait_for_timeout(1000)
    hotbar_btn = None

    # Step A: Check calibrated video_mode_menu selector first
    vm_menu_sel = sels.get("video_mode_menu")
    if vm_menu_sel:
        try:
            c_sel = clean_selector(vm_menu_sel)
            loc = page.locator(c_sel)
            cnt = loc.count()
            for idx in range(cnt):
                b = loc.nth(idx)
                if b.is_visible() and not is_project_header_element(b, sels):
                    hotbar_btn = b
                    ui.log(f"[{n}] found 3-dots button via calibrated 'video_mode_menu' selector")
                    break
        except Exception as e:
            ui.log(f"   calibrated video_mode_menu check notice: {e}")

    # Step B: Check inside the tile's parent container
    if not hotbar_btn and container and container.count() > 0:
        try:
            candidates = container.locator(
                "flow-image-hotbar button, flow-hotbar-container button, button[aria-label*='More' i], button:has-text('more_vert')"
            ).all()
            for b in candidates:
                if b.is_visible() and not is_project_header_element(b, sels):
                    hotbar_btn = b
                    ui.log(f"[{n}] found 3-dots button inside tile container hotbar")
                    break
        except Exception:
            pass

    # Step C: Check any visible hotbar on page
    if not hotbar_btn:
        try:
            hotbars = page.locator("flow-image-hotbar, flow-hotbar-container").all()
            for hb in hotbars:
                if hb.is_visible():
                    btns = hb.locator("button").all()
                    for b in btns:
                        if b.is_visible() and not is_project_header_element(b, sels):
                            txt = (b.get_attribute("aria-label") or "") + " " + (b.inner_text() or "")
                            if any(w in txt.lower() for w in ["more", "option", "vert"]):
                                hotbar_btn = b
                                ui.log(f"[{n}] found 3-dots button in active hotbar via label: '{txt.strip()}'")
                                break
                    if not hotbar_btn and len(btns) >= 3:
                        hotbar_btn = btns[2]  # 3rd button
                        ui.log(f"[{n}] chosen 3rd button in active hotbar")
                    elif not hotbar_btn and btns:
                        hotbar_btn = btns[-1]
                        ui.log(f"[{n}] chosen last button in active hotbar")
                    if hotbar_btn:
                        break
        except Exception:
            pass

    # Step D: Fallback to any visible canvas more-options button not in project header
    if not hotbar_btn:
        try:
            all_more = page.locator('button[aria-label*="More" i], button:has-text("more_vert")').all()
            valid = [b for b in all_more if b.is_visible() and not is_project_header_element(b, sels)]
            if valid:
                hotbar_btn = valid[0] if cfg.get("newest_tile", "first") == "first" else valid[-1]
                ui.log(f"[{n}] found non-header 3-dots button on canvas")
        except Exception:
            pass

    if hotbar_btn:
        ui.log(f"[{n}] clicking 3-dots button on image card...")
        click_loc(page, hotbar_btn, timeout=4000, force=True)
    else:
        ui.log(f"[{n}] ⚠ Could not locate 3-dots button on card hotbar. Attempting direct video mode search...")

    # Check if menu overlay opened
    menu_visible = False
    try:
        menu_loc = page.locator("flow-image-context-menu-items, flow-media-context-menu-items, [role='menu'], mat-menu-content, .mat-mdc-menu-panel").first
        if menu_loc.is_visible():
            menu_visible = True
            ui.log(f"[{n}] image options menu is open")
    except Exception:
        pass

    if not menu_visible:
        ui.log(f"[{n}] ⚠ Note: menu overlay not yet detected; will proceed with video mode selection.")

    page.wait_for_timeout(1000)
    return bool(hotbar_btn) or menu_visible


# ----------------------------------------------------------------- calibrate
def choose(page, cands, multi):
    """Pick the best candidate selector. Returns (selector, match_count)."""
    for c in cands:
        if multi and ":nth-of-type" in c:
            continue
        n = count(page, c)
        if n == 1:
            return c, n
        if multi and n > 0:
            return c, n

    best = None
    for c in cands:
        n = count(page, c)
        if 0 < n <= 4:
            return c, n
        if n > 4 and any(attr in c for attr in ['aria-label', ':has-text', 'data-testid', '#']):
            if best is None or n < best[1]:
                best = (c, n)

    if best:
        return best

    for c in cands:
        if any(attr in c for attr in ['aria-label', ':has-text', 'data-testid', '#']):
            return c, 0

    return (cands[0], 0) if cands else (None, 0)


def calibrate(cfg, ui):
    sels = load_selectors()
    got = queue.Queue()
    ui.paused.clear()
    with sync_playwright() as pw:
        ctx = launch(pw, cfg, ui)

        def on_report(raw_str):
            try:
                data = json.loads(raw_str)
                if isinstance(data, dict) and data.get("action") == "toggle_pause":
                    if ui.paused.is_set():
                        ui.paused.clear()
                        ui.set_pause_state(False)
                        ui.log("▶ Calibration resumed.")
                    else:
                        ui.paused.set()
                        ui.set_pause_state(True)
                        ui.log("⏸ Calibration paused. Browser clicks will not be recorded until you resume.")
                    return
            except Exception:
                pass
            if not ui.paused.is_set():
                got.put(raw_str)

        ctx.expose_function("__flowReport", on_report)
        ctx.add_init_script(CAPTURE_JS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["project_url"] or cfg["flow_url"])
        ui.log("Calibration started. Do ONE real image->video pair by hand, "
               "following the instruction shown in the app for each step.")
        ui.log("💡 TIP: You can click 'Pause calibration' in the app (or the floating button in the browser, or Alt+P) "
               "at any time to interact freely without recording clicks.")
        try:
            for i, (key, text, multi) in enumerate(STEPS, 1):
                ui.skip.clear()
                while not got.empty():
                    got.get_nowait()
                ui.step(f"Step {i}/{len(STEPS)}: {text}", True)
                while True:
                    check_stop(ui)
                    if ui.skip.is_set():
                        ui.log(f"   skipped {key}" + (" (kept old value)" if key in sels else ""))
                        break

                    try:
                        if page.is_closed() or not ctx.pages:
                            ui.log("ℹ Browser was closed. Exiting calibration.")
                            return
                    except Exception:
                        ui.log("ℹ Browser was closed. Exiting calibration.")
                        return

                    if ui.paused.is_set():
                        while not got.empty():
                            got.get_nowait()
                        ui.step(f"⏸ [PAUSED] Step {i}/{len(STEPS)}: Calibration paused. "
                                f"Interact freely with the browser. "
                                f"Click 'Resume calibration' (or in browser, or Alt+P) when ready.", True)
                        try:
                            page.evaluate("window.__flowSetPaused && window.__flowSetPaused(true)")
                        except Exception:
                            pass
                        while ui.paused.is_set() and not ui.stop.is_set() and not ui.skip.is_set():
                            try:
                                if page.is_closed() or not ctx.pages:
                                    ui.log("ℹ Browser was closed. Exiting calibration.")
                                    return
                                page.wait_for_timeout(200)
                            except (TargetClosedError, Exception):
                                ui.log("ℹ Browser was closed. Exiting calibration.")
                                return
                        if ui.skip.is_set():
                            ui.paused.clear()
                            ui.set_pause_state(False)
                            ui.log(f"   skipped {key}" + (" (kept old value)" if key in sels else ""))
                            break
                        try:
                            page.evaluate("window.__flowSetPaused && window.__flowSetPaused(false)")
                        except Exception:
                            pass
                        while not got.empty():
                            got.get_nowait()
                        ui.step(f"Step {i}/{len(STEPS)}: {text}", True)
                        continue

                    try:
                        raw = got.get_nowait()
                    except queue.Empty:
                        try:
                            if page.is_closed() or not ctx.pages:
                                ui.log("ℹ Browser was closed. Exiting calibration.")
                                return
                            page.wait_for_timeout(250)
                        except (TargetClosedError, Exception):
                            ui.log("ℹ Browser was closed. Exiting calibration.")
                            return
                        continue
                    candidates = json.loads(raw)
                    ui.log(f"   raw candidates: {candidates[:3]}")
                    sel, n = choose(page, candidates, multi)
                    if not sel:
                        ui.log("   ⚠ no usable selector found — click the element again")
                        continue
                    sels[key] = sel
                    save_selectors(sels)
                    note = "" if n else "  (could not verify - check it later)"
                    ui.log(f"   ✓ {key} = {sel}   [{n} match(es)]{note}")
                    # Warn if a critical step captured something suspicious
                    suspect = False
                    if key in ("image_result", "video_result") and (
                        "Settings" in sel or "generation" in sel.lower() or "Back" in sel
                    ):
                        suspect = True
                    if key in ("image_generate", "video_generate") and "Settings" in sel:
                        suspect = True
                    if suspect:
                        ui.log(f"   ⚠ WARNING: '{sel}' looks suspicious for {key}. "
                                f"Did you click the right element? If not, re-do this step.")
                    break
            ui.log("Calibration finished. Selectors saved to selectors.json")
        except Stopped:
            ui.log("Calibration stopped. Steps captured so far were saved.")
        except (TargetClosedError, Exception) as e:
            msg = str(e)
            if "Target closed" in msg or "closed" in msg.lower() or isinstance(e, TargetClosedError):
                ui.log("ℹ Browser was closed. Calibration ended.")
            else:
                ui.log(f"Calibration ended: {e}")
        finally:
            ui.paused.clear()
            ui.step("", False)
            try:
                ctx.close()
            except Exception:
                pass


def calibrate_single_step(cfg, ui, target_key):
    """Calibrate only one specific step without repeating all other steps."""
    sels = load_selectors()
    step_info = next((s for s in STEPS if s[0] == target_key), None)
    if not step_info:
        ui.log(f"Unknown calibration step: {target_key}")
        return
    key, text, multi = step_info
    got = queue.Queue()
    ui.paused.clear()
    with sync_playwright() as pw:
        ctx = launch(pw, cfg, ui)

        def on_report(raw_str):
            try:
                data = json.loads(raw_str)
                if isinstance(data, dict) and data.get("action") == "toggle_pause":
                    if ui.paused.is_set():
                        ui.paused.clear()
                        ui.set_pause_state(False)
                        ui.log("▶ Calibration resumed.")
                    else:
                        ui.paused.set()
                        ui.set_pause_state(True)
                        ui.log("⏸ Calibration paused. Browser clicks will not be recorded until you resume.")
                    return
            except Exception:
                pass
            if not ui.paused.is_set():
                got.put(raw_str)

        ctx.expose_function("__flowReport", on_report)
        ctx.add_init_script(CAPTURE_JS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["project_url"] or cfg["flow_url"])
        ui.log(f"🎯 Recalibrating single step: [{key}]")
        ui.log(f"Instruction: {text}")
        ui.log("💡 TIP: Interact with the page freely or use Pause/Resume, then click the target element.")
        ui.skip.clear()
        ui.step(f"🎯 Recalibrating [{key}]: {text}", True)

        try:
            while True:
                check_stop(ui)
                if ui.skip.is_set():
                    ui.log(f"   skipped {key}" + (" (kept old value)" if key in sels else ""))
                    break

                try:
                    if page.is_closed() or not ctx.pages:
                        ui.log("ℹ Browser was closed. Exiting recalibration.")
                        return
                except Exception:
                    ui.log("ℹ Browser was closed. Exiting recalibration.")
                    return

                if ui.paused.is_set():
                    while not got.empty():
                        got.get_nowait()
                    ui.step(f"⏸ [PAUSED] Recalibrating [{key}]: Calibration paused. "
                            f"Interact freely with the browser. Click 'Resume calibration' when ready.", True)
                    try:
                        page.evaluate("window.__flowSetPaused && window.__flowSetPaused(true)")
                    except Exception:
                        pass
                    while ui.paused.is_set() and not ui.stop.is_set() and not ui.skip.is_set():
                        try:
                            if page.is_closed() or not ctx.pages:
                                ui.log("ℹ Browser was closed. Exiting recalibration.")
                                return
                            page.wait_for_timeout(200)
                        except (TargetClosedError, Exception):
                            ui.log("ℹ Browser was closed. Exiting recalibration.")
                            return
                    if ui.skip.is_set():
                        ui.paused.clear()
                        ui.set_pause_state(False)
                        ui.log(f"   skipped {key}" + (" (kept old value)" if key in sels else ""))
                        break
                    try:
                        page.evaluate("window.__flowSetPaused && window.__flowSetPaused(false)")
                    except Exception:
                        pass
                    while not got.empty():
                        got.get_nowait()
                    ui.step(f"🎯 Recalibrating [{key}]: {text}", True)
                    continue

                try:
                    raw = got.get_nowait()
                except queue.Empty:
                    try:
                        if page.is_closed() or not ctx.pages:
                            ui.log("ℹ Browser was closed. Exiting recalibration.")
                            return
                        page.wait_for_timeout(250)
                    except (TargetClosedError, Exception):
                        ui.log("ℹ Browser was closed. Exiting recalibration.")
                        return
                    continue

                candidates = json.loads(raw)
                ui.log(f"   raw candidates: {candidates[:3]}")
                sel, n = choose(page, candidates, multi)
                if not sel:
                    ui.log("   ⚠ no usable selector found — click the element again")
                    continue
                sels[key] = sel
                save_selectors(sels)
                note = "" if n else "  (could not verify - check it later)"
                ui.log(f"   ✓ {key} = {sel}   [{n} match(es)]{note}")
                break
            ui.log(f"🎯 Recalibration for '{key}' complete! Saved to selectors.json")
        except Stopped:
            ui.log("Recalibration stopped.")
        except (TargetClosedError, Exception) as e:
            msg = str(e)
            if "Target closed" in msg or "closed" in msg.lower() or isinstance(e, TargetClosedError):
                ui.log("ℹ Browser was closed. Recalibration ended.")
            else:
                ui.log(f"Recalibration ended: {e}")
        finally:
            ui.paused.clear()
            ui.step("", False)
            try:
                ctx.close()
            except Exception:
                pass


# ----------------------------------------------------------------- login
def login(cfg, ui):
    with sync_playwright() as pw:
        ctx = launch(pw, cfg, ui)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["project_url"] or cfg["flow_url"])
        ui.log("Browser opened. Log into Google / Flow manually, then CLOSE the browser window.")
        try:
            while not ui.stop.is_set() and ctx.pages:
                if page.is_closed():
                    break
                page.wait_for_timeout(500)
        except (TargetClosedError, Exception):
            pass
        try:
            ctx.close()
        except Exception:
            pass
        ui.log("Login session saved in the profile folder.")


# ----------------------------------------------------------------- main run
def process_pair(page, cfg, sels, n, img_prompt, vid_prompt, ui):
    start_url = cfg["project_url"] or cfg["flow_url"]

    if cfg.get("reload_each_pair", False):
        page.goto(start_url)
        page.wait_for_timeout(3000)

    before_srcs = set()
    if cfg.get("skip_image_gen", False):
        ui.log(f"[{n}] 🧪 [TEST MODE] Skipping image generation — using existing canvas image tile...")
        if hasattr(ui, "pair_stage"):
            ui.pair_stage(n, "image", "ok")
        page.wait_for_timeout(2000)
    else:
        # ---- image
        if hasattr(ui, "pair_stage"):
            ui.pair_stage(n, "image", "work")
        ui.log(f"[{n}] entering image prompt...")
        wait_visible(page, sels["image_prompt_box"], 60)
        fill(page, sels["image_prompt_box"], img_prompt)
        ui.log(f"[{n}] prompt entered, clicking generate")
        before_count = count(page, sels["image_result"])
        before_srcs = set(get_tile_srcs(page, sels["image_result"]))
        pause(cfg, ui)
        click(page, sels["image_generate"])
        wait_new(page, sels["image_result"], before_count, before_srcs, cfg["image_timeout"], ui, "image", prompt=img_prompt, pair_index=n)
        page.wait_for_timeout(int(cfg.get("settle_image", 3) * 1000))
        if hasattr(ui, "pair_stage"):
            ui.pair_stage(n, "image", "ok")
        ui.log(f"[{n}] ✓ image ready!")

    # ---- video
    if hasattr(ui, "pair_stage"):
        ui.pair_stage(n, "video", "work")
    ui.log(f"[{n}] image -> video")
    tile = pick_target_tile(page, sels["image_result"], before_srcs if not cfg.get("skip_image_gen") else set(), cfg)
    open_image_context_menu(page, tile, sels, cfg, ui, n)
    pause(cfg, ui)

    # Click video_mode
    ui.log(f"[{n}] selecting video mode...")
    video_mode_clicked = False
    if sels.get("video_mode"):
        try:
            click(page, sels["video_mode"], timeout=6000)
            video_mode_clicked = True
        except Exception as e:
            ui.log(f"   video_mode selector '{sels['video_mode']}' failed ({e}), searching menu alternatives...")

    if not video_mode_clicked:
        try:
            candidates = page.locator("flow-image-context-menu-items button, flow-media-context-menu-items button, [role='menu'] button, [role='menuitem'], .mat-mdc-menu-item").all()
            for btn in candidates:
                txt = (btn.inner_text() or "").strip()
                label = btn.get_attribute("aria-label") or ""
                combined = (txt + " " + label).lower()
                if any(w in combined for w in ["add to prompt", "video", "animate", "prompt", "motion"]):
                    ui.log(f"   clicked video mode option via text/label: '{txt or label}'")
                    click_loc(page, btn, timeout=4000, force=True)
                    video_mode_clicked = True
                    break
        except Exception as ex:
            ui.log(f"   fallback search warning: {ex}")

    if not video_mode_clicked:
        if hasattr(ui, "pair_stage"):
            ui.pair_stage(n, "video", "err")
        raise RuntimeError(
            f"Could not switch to video mode for item #{n}. The options menu did not open or video mode was not found. "
            f"Please check if canvas is visible and recalibrate 'video_mode_menu' / 'video_mode' if needed."
        )
    pause(cfg, ui)
    ui.log(f"[{n}] entering video prompt...")
    wait_visible(page, sels["video_prompt_box"], 60)
    fill(page, sels["video_prompt_box"], vid_prompt)
    ui.log(f"[{n}] video prompt entered, clicking generate")
    before_vid_count = count(page, sels["video_result"])
    before_vid_srcs = set(get_tile_srcs(page, sels["video_result"]))
    pause(cfg, ui)
    click(page, sels["video_generate"])
    wait_new(page, sels["video_result"], before_vid_count, before_vid_srcs, cfg["video_timeout"], ui, "video", prompt=vid_prompt, pair_index=n)
    if hasattr(ui, "pair_stage"):
        ui.pair_stage(n, "video", "ok")
    ui.log(f"[{n}] ✓ Video #{n} generated and verified on Google Flow canvas!")
    page.wait_for_timeout(int(cfg.get("settle_video", 5) * 1000))


def _move_script_to_completed(script_path_str, ui):
    try:
        sp = Path(script_path_str)
        if sp.exists():
            comp_dir = sp.parent / "completed"
            comp_dir.mkdir(parents=True, exist_ok=True)
            dest = comp_dir / sp.name
            shutil.move(str(sp), str(dest))
            ui.log(f"📦 Moved completed script '{sp.name}' to completed/ folder.")
        else:
            ui.log(f"ℹ Script file {sp.name} already moved or not found.")
    except Exception as e:
        ui.log(f"⚠ Could not move script file to completed: {e}")


def get_pending_scripts(scripts_dir):
    """Return all pending .md script files in scripts/ (excluding completed/)."""
    p = Path(scripts_dir)
    if not p.exists():
        return []
    return [f for f in sorted(p.glob("*.md")) if f.is_file() and f.parent == p]


def run_batch(cfg, pairs, ui):
    """Run batch queue: processes prompt pairs across scripts until queue is empty."""
    import import_script as importer

    sels = load_selectors()
    missing = [k for k in REQUIRED if k not in sels]
    if missing:
        ui.log("Missing selectors: " + ", ".join(missing))
        ui.log("Run 'Calibrate selectors' first.")
        return

    LOGS_DIR.mkdir(exist_ok=True)
    scripts_dir = abs_path(cfg.get("scripts_dir", "scripts"))
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "completed").mkdir(exist_ok=True)

    with sync_playwright() as pw:
        ctx = None
        page = None
        try:
            ctx = launch(pw, cfg, ui)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(cfg["project_url"] or cfg["flow_url"])
            page.wait_for_timeout(3000)
        except (Stopped, TargetClosedError) as e:
            ui.log("⏹ Browser closed or task stopped during launch/navigation.")
            return
        except Exception as launch_err:
            err_str = str(launch_err)
            if (TargetClosedError and isinstance(launch_err, TargetClosedError)) or "TargetClosedError" in type(launch_err).__name__ or "Target page, context or browser has been closed" in err_str:
                ui.log("⏹ Browser closed during launch/navigation. Stopped cleanly.")
                return
            raise

        def get_healthy_page():
            nonlocal ctx, page
            check_stop(ui)
            try:
                if ctx and not page.is_closed():
                    return page
            except Exception:
                pass
            check_stop(ui)
            ui.log("   ⚠ Browser page was closed/disconnected; reconnecting project page...")
            try:
                if ctx and ctx.pages and not ctx.pages[0].is_closed():
                    page = ctx.pages[0]
                    page.goto(cfg["project_url"] or cfg["flow_url"])
                    page.wait_for_timeout(3000)
                    return page
                elif ctx:
                    page = ctx.new_page()
                    page.goto(cfg["project_url"] or cfg["flow_url"])
                    page.wait_for_timeout(3000)
                    return page
            except Exception:
                pass
            check_stop(ui)
            ui.log("   ⚠ Browser session was closed/crashed; relaunching Chromium...")
            try:
                if ctx:
                    ctx.close()
            except Exception:
                pass
            ctx = launch(pw, cfg, ui)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(cfg["project_url"] or cfg["flow_url"])
            page.wait_for_timeout(3000)
            return page

        # Queue loop: continue until all scripts in scripts/ are finished
        raw_script = cfg.get("script_file")
        current_script_path = Path(raw_script) if raw_script and Path(raw_script).exists() else None
        if current_script_path and (current_script_path.parent.name == "completed" or not current_script_path.exists()):
            current_script_path = None
        current_pairs = pairs
        processed_scripts_in_session = set()

        try:
            while True:
                check_stop(ui)
                pending_files = [s for s in get_pending_scripts(scripts_dir) if str(s.resolve()) not in processed_scripts_in_session]

                if not current_script_path:
                    if pending_files:
                        current_script_path = pending_files[0]
                        current_pairs = importer.parse_script_file(current_script_path)[:8]
                        ui.log(f"📂 Loaded next script from queue: {current_script_path.name} ({len(current_pairs)} pairs)")
                    else:
                        ui.log("🏁 All scripts in queue have been processed! No pending scripts found in scripts/ folder.")
                        clear_batch_state()
                        break

                script_name = current_script_path.name if current_script_path else "Custom Prompts"
                active_pairs = current_pairs or []
                total_pairs = len(active_pairs)

                if total_pairs == 0:
                    ui.log(f"⚠ Script '{script_name}' has 0 prompt pairs. Skipping...")
                    if current_script_path and cfg.get("move_script_when_done", True):
                        _move_script_to_completed(str(current_script_path), ui)
                    if current_script_path:
                        processed_scripts_in_session.add(str(current_script_path.resolve()))
                    current_script_path = None
                    current_pairs = []
                    continue

                # Incorporate resume_from index if set
                resume_from = int(cfg.get("resume_pair_index", 1))

                # If starting fresh from pair 1, completely reset script state
                if resume_from <= 1:
                    if current_script_path:
                        clear_script_state(current_script_path)
                    saved_script_state = None
                    completed_indices = set()
                    failed_pairs_list = []
                    policy_violations_list = []
                else:
                    saved_script_state = load_script_state(current_script_path) if current_script_path else None
                    completed_indices = set(saved_script_state.get("completed_pairs", [])) if saved_script_state else set()
                    failed_pairs_list = list(saved_script_state.get("failed_pairs", [])) if saved_script_state else []
                    policy_violations_list = list(saved_script_state.get("policy_violations", [])) if saved_script_state else []
                    # Strictly guarantee failed pairs are excluded from completed
                    failed_nums = {f.get("pair") for f in failed_pairs_list if isinstance(f, dict) and f.get("pair")}
                    completed_indices = {c for c in completed_indices if c not in failed_nums}

                ui.log(f"\n=======================================================")
                ui.log(f"🎬 PROCESSING SCRIPT: {script_name}")
                if completed_indices:
                    ui.log(f"🔄 SAVED STATE DETECTED: {len(completed_indices)} pair(s) already completed. They will be skipped to protect tokens.")
                if resume_from > 1:
                    ui.log(f"🔄 RESUMING BATCH: Starting from Pair #{resume_from} of {total_pairs}")
                else:
                    ui.log(f"📊 Target: {total_pairs} video prompt pair(s)")
                ui.log(f"📦 Pending scripts in queue: {len(pending_files)}")
                ui.log(f"=======================================================\n")

                # Save initial active running state
                script_state_data = {
                    "script_file": str(current_script_path) if current_script_path else "",
                    "script_name": script_name,
                    "current_pair_index": resume_from,
                    "total_pairs": total_pairs,
                    "completed_pairs": sorted(list(completed_indices)),
                    "failed_pairs": failed_pairs_list,
                    "policy_violations": policy_violations_list,
                    "status": "running",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "output_dir": str(cfg.get("output_dir", ""))
                }
                save_batch_state(script_state_data)
                if current_script_path:
                    save_script_state(current_script_path, script_state_data)

                if hasattr(ui, "queue_progress"):
                    ui.queue_progress(script_name, len(completed_indices), total_pairs, len(pending_files))

                for n, (img_p, vid_p) in enumerate(active_pairs, 1):
                    check_stop(ui)
                    if resume_from > 1 and n < resume_from:
                        if n in completed_indices:
                            ui.log(f"[{n}/{total_pairs}] ⏩ Pair #{n} was already completed. Skipping to save tokens.")
                        else:
                            ui.log(f"[{n}/{total_pairs}] ⏩ Pair #{n} skipped (resuming batch from Pair #{resume_from}).")
                        continue

                    if n in completed_indices:
                        ui.log(f"[{n}/{total_pairs}] ⏩ Pair #{n} was already completed. Skipping to save tokens.")
                        continue

                    # Update persistent running state before starting pair
                    script_state_data["current_pair_index"] = n
                    script_state_data["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    save_batch_state(script_state_data)
                    if current_script_path:
                        save_script_state(current_script_path, script_state_data)

                    ui.step(f"[{script_name}] Generating Pair #{n}/{total_pairs}...", False)
                    pair_success = False

                    for attempt in range(1, cfg["max_retries"] + 2):
                        try:
                            page = get_healthy_page()
                            process_pair(page, cfg, sels, n, img_p, vid_p, ui)
                            pair_success = True
                            break
                        except Stopped:
                            script_state_data["status"] = "stopped"
                            script_state_data["current_pair_index"] = n
                            script_state_data["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                            save_batch_state(script_state_data)
                            if current_script_path:
                                save_script_state(current_script_path, script_state_data)
                            raise
                        except PolicyViolationError as pve:
                            ui.log(f"[{n}/{total_pairs}] ⚠️ [POLICY VIOLATION] Google Flow flagged prompt: {pve.message}")
                            record_policy_violation(
                                script_name=script_name,
                                pair_index=n,
                                img_prompt=img_p,
                                vid_prompt=vid_p,
                                reason=pve.message,
                                stage=pve.stage,
                                output_dir=cfg.get("output_dir", "")
                            )
                            pol_entry = {"pair": n, "reason": pve.message, "stage": pve.stage, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
                            policy_violations_list.append(pol_entry)

                            on_reject = cfg.get("on_reject_action", "Ask me")
                            if hasattr(ui, "pair_error"):
                                ui.pair_error(script_name, n, total_pairs, pve.stage, "policy_violation", pve.message)

                            decision = "skip"
                            if on_reject == "Stop the batch":
                                ui.log(f"   Action: Configured to stop on reject. Stopping batch now.")
                                script_state_data["status"] = "stopped"
                                script_state_data["current_pair_index"] = n
                                save_batch_state(script_state_data)
                                if current_script_path:
                                    save_script_state(current_script_path, script_state_data)
                                raise Stopped()
                            elif on_reject == "Ask me" and hasattr(ui, "ask_decision"):
                                ui.log(f"   Action: Waiting for your decision (Retry, Edit, or Skip)...")
                                decision = ui.ask_decision(n, pve.stage, pve.message)

                            if decision == "retry":
                                ui.log(f"   Action: Retrying Pair #{n} as requested...")
                                continue
                            elif decision == "stop":
                                script_state_data["status"] = "stopped"
                                script_state_data["current_pair_index"] = n
                                save_batch_state(script_state_data)
                                if current_script_path:
                                    save_script_state(current_script_path, script_state_data)
                                raise Stopped()
                            else:  # skip
                                ui.log(f"   Action: Skipping Pair #{n} to protect tokens and continue queue.")
                                completed_indices.discard(n)
                                failed_pairs_list.append({
                                    "pair": n,
                                    "stage": pve.stage,
                                    "reason": f"Policy violation: {pve.message}",
                                    "image_prompt": img_p,
                                    "video_prompt": vid_p,
                                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
                                })
                                script_state_data["current_pair_index"] = n + 1
                                script_state_data["failed_pairs"] = failed_pairs_list
                                script_state_data["completed_pairs"] = sorted(list(completed_indices))
                                script_state_data["policy_violations"] = policy_violations_list
                                script_state_data["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                                save_batch_state(script_state_data)
                                if current_script_path:
                                    save_script_state(current_script_path, script_state_data)
                                if hasattr(ui, "pair_stage"):
                                    ui.pair_stage(n, "image", "skip")
                                    ui.pair_stage(n, "video", "skip")
                                if hasattr(ui, "queue_progress"):
                                    ui.queue_progress(script_name, len(completed_indices), total_pairs, len(pending_files))
                                break
                        except Exception as e:
                            err_line = str(e).splitlines()[0] if str(e) else "Unknown error"
                            ui.log(f"[{n}/{total_pairs}] attempt {attempt} failed: {err_line}")
                            try:
                                if not page.is_closed():
                                    page.screenshot(path=str(LOGS_DIR / f"fail_{n}_{attempt}.png"))
                            except Exception:
                                pass
                            if attempt > cfg["max_retries"]:
                                ui.log(f"[{n}/{total_pairs}] ❌ Pair #{n} failed after {cfg['max_retries']} retries: {err_line}")
                                ui.log(f"   Action: Skipping Pair #{n} and recording failure in state so batch can continue without repeating.")
                                completed_indices.discard(n)
                                failed_pairs_list.append({
                                    "pair": n,
                                    "stage": "generation",
                                    "reason": err_line,
                                    "image_prompt": img_p,
                                    "video_prompt": vid_p,
                                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
                                })
                                script_state_data["current_pair_index"] = n + 1
                                script_state_data["failed_pairs"] = failed_pairs_list
                                script_state_data["completed_pairs"] = sorted(list(completed_indices))
                                script_state_data["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                                save_batch_state(script_state_data)
                                if current_script_path:
                                    save_script_state(current_script_path, script_state_data)
                                if hasattr(ui, "pair_stage"):
                                    ui.pair_stage(n, "image", "err")
                                    ui.pair_stage(n, "video", "err")
                                if hasattr(ui, "pair_error"):
                                    ui.pair_error(script_name, n, total_pairs, "generation", "error", err_line)
                                if hasattr(ui, "queue_progress"):
                                    ui.queue_progress(script_name, len(completed_indices), total_pairs, len(pending_files))

                    if pair_success:
                        completed_indices.add(n)
                        # Remove from failed_pairs_list if previously recorded as failed
                        failed_pairs_list = [f for f in failed_pairs_list if f.get("pair") != n]
                        script_state_data["completed_pairs"] = sorted(list(completed_indices))
                        script_state_data["failed_pairs"] = failed_pairs_list
                        script_state_data["current_pair_index"] = n + 1
                        script_state_data["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                        save_batch_state(script_state_data)
                        if current_script_path:
                            save_script_state(current_script_path, script_state_data)

                        if hasattr(ui, "queue_progress"):
                            ui.queue_progress(script_name, len(completed_indices), total_pairs, len(pending_files))
                        ui.log(f"[{n}/{total_pairs}] ✓ Video generated and verified! Script progress: {len(completed_indices)}/{total_pairs} videos.")

                        # Rate-limit protection: configurable pause between pairs
                        pause_secs = float(cfg.get("pause_between_pairs", 5))
                        if pause_secs > 0 and n < total_pairs:
                            ui.log(f"   Pausing {pause_secs:.0f}s before next pair (avoids rate limits)...")
                            for _ in range(int(pause_secs * 2)):
                                check_stop(ui)
                                time.sleep(0.5)

                # Mark script as processed in this session so it NEVER repeats in the same run
                if current_script_path:
                    processed_scripts_in_session.add(str(current_script_path.resolve()))

                # Script run finished summary
                ui.log(f"📊 Script '{script_name}' finished: {len(completed_indices)}/{total_pairs} videos completed.")
                if failed_pairs_list:
                    ui.log(f"⚠️ Skipped {len(failed_pairs_list)} failed/flagged pairs: {[f.get('pair') for f in failed_pairs_list]}")
                    try:
                        rep_file = SCRIPT_STATES_DIR / f"{Path(script_name).stem}_failures.txt"
                        rep_lines = [f"Failures for {script_name} ({time.strftime('%Y-%m-%d %H:%M:%S')}):"]
                        for f in failed_pairs_list:
                            rep_lines.append(f"  - Pair #{f.get('pair')} [{f.get('stage')}]: {f.get('reason')}")
                        rep_file.write_text("\n".join(rep_lines), encoding="utf-8")
                    except Exception:
                        pass

                is_complete_clean = (len(completed_indices) >= total_pairs and not failed_pairs_list)
                script_state_data["status"] = "completed" if is_complete_clean else "completed_with_errors"
                script_state_data["current_pair_index"] = total_pairs
                script_state_data["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                save_batch_state(script_state_data)
                if current_script_path:
                    save_script_state(current_script_path, script_state_data)

                if is_complete_clean:
                    ui.log(f"🎉 SUCCESS: All {total_pairs} videos for '{script_name}' are generated on Google Flow!")
                    if cfg.get("move_script_when_done", True) and current_script_path:
                        _move_script_to_completed(str(current_script_path), ui)
                else:
                    ui.log(f"⚠️ Script '{script_name}' finished with {len(failed_pairs_list)} error(s). Kept in scripts/ folder for inspection and replay.")

                # Reset current script variables before checking auto-advance
                current_script_path = None
                current_pairs = []
                cfg["resume_pair_index"] = 1

                # Check auto-advance
                if cfg.get("auto_advance_queue", True):
                    pending_after = [s for s in get_pending_scripts(scripts_dir) if str(s.resolve()) not in processed_scripts_in_session]
                    if pending_after:
                        next_script = pending_after[0]
                        ui.log(f"🔄 Auto-advancing queue: Loading next script '{next_script.name}' ({len(pending_after)} remaining)...")
                        current_script_path = next_script
                        current_pairs = importer.parse_script_file(next_script)[:8]
                        page.wait_for_timeout(3000)
                        continue
                    else:
                        ui.log(f"🎉🎉 ALL SCRIPTS FINISHED! All markdown scripts in scripts/ have been processed.")
                        clear_batch_state()
                        break
                else:
                    ui.log(f"Done with '{script_name}'. Auto-advance queue is disabled.")
                    break
        except Stopped:
            ui.log("⏹ Stopped by user.")
        except (TargetClosedError, Exception) as batch_err:
            err_str = str(batch_err)
            if (TargetClosedError and isinstance(batch_err, TargetClosedError)) or "TargetClosedError" in type(batch_err).__name__ or "Target page, context or browser has been closed" in err_str:
                ui.log("⏹ Browser window or session was closed. Batch stopped cleanly.")
            else:
                ui.log(f"⚠ Batch process interrupted: {batch_err}")
                if 'script_name' in locals() and 'n' in locals():
                    save_batch_state({
                        "script_file": str(current_script_path) if current_script_path else "",
                        "script_name": script_name,
                        "current_pair_index": n,
                        "total_pairs": total_pairs if 'total_pairs' in locals() else 0,
                        "completed_pairs": sorted(list(completed_indices)) if 'completed_indices' in locals() else [],
                        "failed_pairs": failed_pairs_list if 'failed_pairs_list' in locals() else [],
                        "policy_violations": policy_violations_list if 'policy_violations_list' in locals() else [],
                        "status": "interrupted",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "output_dir": str(cfg.get("output_dir", ""))
                    })
                raise
        finally:
            try:
                if 'ctx' in locals() and ctx:
                    ctx.close()
            except Exception:
                pass


def test_open_video_mode(cfg, ui):
    """Standalone test: Open browser, activate the latest image tile on canvas,
    open its 3-dot options menu, and click Video mode to verify the interaction."""
    sels = load_selectors()
    ui.log("🧪 [TEST ACTION] Testing: 'Open 3-Dots & Click Video Mode'...")
    with sync_playwright() as pw:
        ctx = launch(pw, cfg, ui)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["project_url"] or cfg["flow_url"])
        page.wait_for_timeout(4000)

        if not sels.get("image_result"):
            ui.log("   ⚠ 'image_result' selector not found in selectors.json. Please calibrate it first.")
            return

        c = count(page, sels["image_result"])
        ui.log(f"   Found {c} image tile(s) matching '{sels['image_result']}' on canvas.")
        if c == 0:
            ui.log("   ⚠ No image tiles found on canvas. Make sure an image exists in the project.")
            return

        tile = pick(page, sels["image_result"], cfg)
        ui.log("   Activating image card options menu...")
        open_image_context_menu(page, tile, sels, cfg, ui, n=1)

        ui.log("   Selecting Video mode option...")
        video_mode_clicked = False
        if sels.get("video_mode"):
            try:
                click(page, sels["video_mode"], timeout=5000)
                video_mode_clicked = True
                ui.log(f"   ✓ Clicked video mode via calibrated selector: '{sels['video_mode']}'")
            except Exception as e:
                ui.log(f"   Calibrated video_mode selector failed ({e}), searching text alternatives...")

        if not video_mode_clicked:
            try:
                candidates = page.locator("flow-image-context-menu-items button, flow-media-context-menu-items button, [role='menu'] button, [role='menuitem'], .mat-mdc-menu-item").all()
                for btn in candidates:
                    txt = (btn.inner_text() or "").strip()
                    label = btn.get_attribute("aria-label") or ""
                    combined = (txt + " " + label).lower()
                    if any(w in combined for w in ["add to prompt", "video", "animate", "prompt", "motion"]):
                        ui.log(f"   ✓ Clicked video mode option via text/label: '{txt or label}'")
                        click_loc(page, btn, timeout=4000, force=True)
                        video_mode_clicked = True
                        break
            except Exception as ex:
                ui.log(f"   Fallback search warning: {ex}")

        if video_mode_clicked:
            ui.log("🎉 SUCCESS: Card 3-dot options menu and Video mode selection verified working!")
        else:
            ui.log("❌ FAILED: Could not click Video mode. Check selectors.json or recalibrate video_mode_menu / video_mode.")

        page.wait_for_timeout(5000)
        try:
            ctx.close()
        except Exception:
            pass


def dismiss_editor_overlay(cfg, ui):
    """Standalone test: Press Escape twice to close any stuck editor modal."""
    ui.log("🧹 [ACTION] Dismissing editor modal via Escape...")
    with sync_playwright() as pw:
        ctx = launch(pw, cfg, ui)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["project_url"] or cfg["flow_url"])
        page.wait_for_timeout(2500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(2000)
        ui.log("✓ Escape key sent. Canvas should now be unobstructed.")
        try:
            ctx.close()
        except Exception:
            pass


def test_all_selectors(cfg, ui):
    """Test all calibrated selectors against the active Flow canvas."""
    sels = load_selectors()
    if not sels:
        ui.log("⚠ No selectors saved yet. Calibrate Flow first.")
        return

    ui.log("🔍 [TEST] Testing calibrated selectors on the current Flow canvas...")
    with sync_playwright() as pw:
        ctx = launch(pw, cfg, ui)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["project_url"] or cfg["flow_url"])
        page.wait_for_timeout(3500)

        ui.log(f"--- SELECTORS VERIFICATION REPORT ({len(sels)} mapped) ---")
        passed = 0
        for key, text, multi in STEPS:
            sel = sels.get(key)
            if not sel:
                ui.log(f"   ⚪ [{key}]: Not calibrated")
                continue
            try:
                c_sel = clean_selector(sel)
                loc = page.locator(c_sel)
                cnt = loc.count()
                vis_cnt = 0
                for i in range(cnt):
                    try:
                        if loc.nth(i).is_visible():
                            vis_cnt += 1
                    except Exception:
                        pass
                if cnt > 0:
                    status = f"✓ Found {cnt} matching element(s) ({vis_cnt} visible)"
                    passed += 1
                else:
                    status = "⚠ 0 matches on current canvas (may need modal/hover or recalibration)"
                ui.log(f"   [{key}]: {status} -> '{sel}'")
            except Exception as e:
                ui.log(f"   [{key}]: ❌ Error checking: {e}")

        ui.log(f"Verification complete: {passed}/{len(sels)} active selectors confirmed on canvas.")
        try:
            ctx.close()
        except Exception:
            pass

