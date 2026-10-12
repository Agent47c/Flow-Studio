# Google Flow Automation: Plan and Design

A Python program that opens Chrome with your saved profile, goes to Google Flow, and runs your list of **image prompts** and **image-to-video prompts** one pair at a time, saving results under custom file names.

---

## 1. Is it possible?

**Yes**, with some caveats:

| Part | Feasible? | Notes |
|---|---|---|
| Open Chrome with a saved login | Yes | Use Playwright with a persistent profile folder |
| Type prompts into Flow and click Generate | Yes | Browser automation can do whatever you can click |
| Wait for generation to finish | Yes | Watch for the result element to appear, with timeouts and retries |
| Select the generated image, then add the video prompt | Yes | This is the most fragile step (see risks) |
| Download and rename outputs | Yes | Intercept the browser download and save under your custom name |
| Run independently (no AI in the loop) | Yes | A normal Python script; no Claude needed at run time |

**Main caveat:** Flow is a web app with no official API for this, so the script clicks buttons by their on-screen selectors. If Google changes the page layout, those selectors break. The design below keeps all selectors in **one file** so a fix is a 2-minute edit.

---

## 2. Important constraints

1. **Do not automate the Google login itself.** Google detects and blocks automated sign-ins. Instead, you log in manually once in the automation profile, and the session is saved.
2. **Chrome 136+ restriction:** Chrome refuses remote-debugging on your *default* profile folder. So the script uses a **dedicated profile folder** (e.g. `./chrome_profile`). You log in there once; it stays logged in afterward. It will not use your everyday Chrome profile directly.
3. **Terms of Service:** Automating a Google product may go against its terms. Heavy or rapid automation can get an account rate-limited or flagged. The script includes human-like delays and limits; consider using a non-critical account.
4. **Credits/quota:** Image and video generation in Flow uses credits. A bug that loops could burn them, so the script has a `--dry-run` mode and a max-retry limit.

---

## 3. Workflow

You said you want it **one pair at a time** (image 1 → video 1, then image 2 → video 2) rather than all images first.

```
for each item i in 1..N:
    1. Open (or stay in) the Flow project
    2. Enter image prompt i  -> Generate
    3. Wait until the image is ready
    4. (optional) Download image as  <name_i>_image.png
    5. Select that generated image
    6. Choose the image-to-video option
    7. Enter video prompt i  -> Generate
    8. Wait until the video is ready
    9. Download video as  <name_i>_video.mp4
   10. Record "item i done" in state file
```

**Resume support:** a `state.json` file records finished items. If the script crashes at item 5, running it again continues from item 5 instead of starting over.

---

## 4. Project structure

```
flow_automation/
├── run.py                # entry point (CLI)
├── config.yaml           # all your settings and prompts (or point to a CSV)
├── prompts.csv           # optional: one row per item
├── flow_selectors.py     # ALL page selectors live here (the only file to fix if Flow changes)
├── flow_driver.py        # functions: open_flow, submit_image_prompt, select_image, ...
├── state.json            # auto-created progress tracker
├── chrome_profile/       # auto-created; your saved login
├── output/               # downloaded images and videos
└── logs/                 # run logs + screenshots on failure
```

---

## 5. Configuration (custom names and settings)

`config.yaml`:

```yaml
flow_url: "https://labs.google/fx/tools/flow"
profile_dir: "./chrome_profile"
output_dir: "./output"

# Custom naming. Placeholders: {index} {slug} {type} {date}
naming:
  image: "{index:02d}_{slug}_image"
  video: "{index:02d}_{slug}_video"

settings:
  headless: false            # keep false so you can watch / solve captchas
  image_timeout_sec: 240
  video_timeout_sec: 900
  max_retries: 2
  delay_between_actions_sec: [1.5, 4.0]   # random range, looks more natural
  download_images: true

items:
  - slug: "sunrise-city"
    image_prompt: "A wide cinematic shot of a city at sunrise, golden light"
    video_prompt: "Slow camera push-in, clouds drifting, cars moving below"
  - slug: "forest-path"
    image_prompt: "A misty forest path with sunbeams"
    video_prompt: "Gentle forward walk through the mist, leaves swaying"
  # ... up to 8 (or any number)
```

Alternative: keep prompts in `prompts.csv` with columns `slug,image_prompt,video_prompt` and set `prompts_file: prompts.csv` in the config.

---

## 6. How it runs

```bash
pip install playwright pyyaml
playwright install chromium        # or use your installed Chrome via channel="chrome"

# First time only: opens the browser so YOU log into Google manually
python run.py --login

# Normal run
python run.py --config config.yaml

# Useful options
python run.py --only 3,4           # run only items 3 and 4
python run.py --from 5             # start from item 5
python run.py --dry-run            # fill prompts but do NOT click Generate
python run.py --reset              # ignore state.json and start over
```

Core of the driver (sketch):

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=cfg["profile_dir"],
        channel="chrome",          # use real Chrome
        headless=False,
        accept_downloads=True,
        viewport={"width": 1440, "height": 900},
    )
    page = ctx.new_page()
    page.goto(cfg["flow_url"])
    for i, item in enumerate(items, 1):
        if state.is_done(i):
            continue
        submit_image_prompt(page, item["image_prompt"])
        wait_for_image(page, timeout=cfg["settings"]["image_timeout_sec"])
        select_latest_image(page)
        submit_video_prompt(page, item["video_prompt"])
        video_path = wait_and_download_video(page, name=make_name("video", i, item))
        state.mark_done(i, video_path)
```

---

## 7. Making it reliable

- **Selectors in one file**, preferring stable ones (visible text, ARIA roles, `data-*` attributes) over fragile CSS class names that change on every deploy.
- **Explicit waits**, never fixed `sleep()` for generation. Wait for the "done" state with a timeout.
- **Retries** with a screenshot and HTML dump saved to `logs/` on every failure so you can see exactly what went wrong.
- **State file + resume** so a crash never costs you finished work.
- **Random delays** between actions to avoid looking like a bot and to reduce rate-limit hits.
- **Stop conditions:** detects a login page, captcha, "quota exceeded", or "generation failed" messages and pauses/exits cleanly instead of looping.
- **Unique-image tracking:** after generating image *i*, the script records which tile is new (by count or ID) so it selects the correct image and not an older one.
- **Never hard-code credentials.** Login stays manual.

---

## 8. Known risks

| Risk | Mitigation |
|---|---|
| Google changes the Flow UI | Selectors isolated in `flow_selectors.py`; failure screenshots |
| Selecting the wrong generated image | Track tile count/ID before and after generating |
| Flow generates several images per prompt | Config option for which one to pick (first / index N) |
| Video generation is slow or fails | Long timeout, retry, and resume |
| Session expires | Script detects the login page and asks you to run `--login` again |
| Rate limits or credit exhaustion | Detect the message, stop, and keep progress |

---

## 9. Questions I need answered

These decide how the script is built, so please answer what you can:

1. **Images:** Do you want Flow to **generate** the images from your 8 image prompts, or will you **upload your own** images and only use the video prompts?
2. **Flow mode:** Which mode in Flow do you use for the video step (for example *Frames to Video*, *Ingredients to Video*, or *Text to Video*)? And which model/quality setting do you want selected?
3. **Multiple results:** When Flow generates an image, it may produce more than one variation. Should the script pick the **first**, the **last**, or a specific number?
4. **Project:** Should every run use a **new Flow project**, or an **existing project** (give me its URL)?
5. **Downloads:** Do you want to download the **images too**, or only the final videos? Any preferred quality/resolution option?
6. **Naming:** What file name pattern do you want? Example: `01_sunrise-city_video.mp4`. Do you want a date or project name in it?
7. **Prompt input:** Do you prefer prompts in a **YAML config**, a **CSV/Excel file**, or a simple **text file**?
8. **Account/OS:** Which operating system are you using (Windows, Mac, Linux)? And is the Google account one that can safely be used for automation?
9. **Agent mode:** You mentioned an "agent mode" that generates everything at once. Do you want the script to use that, or follow the one-pair-at-a-time flow described above? (The one-pair flow is more predictable.)
10. **Screenshots:** Can you share a few screenshots of the Flow screens (prompt box, generated image, the "image to video" step)? This lets me write accurate selectors instead of guessing.

---

## 10. Suggested next steps

1. Answer the questions above (especially 1, 2, 9 and 10).
2. I write the working script: `run.py`, `flow_driver.py`, `flow_selectors.py`, `config.yaml`.
3. You run `--login` once, then `--dry-run` to confirm the prompts land in the right boxes.
4. Run a single item first (`--only 1`), then the full batch.
