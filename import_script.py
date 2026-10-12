"""Script to parse prompt pairs from markdown scripts (like brandy-script.md)
and automatically save them into settings.json for the I-TO-V Tool.

Usage:
    python import_script.py                    # Imports brandy-script.md or auto-detected .md
    python import_script.py <path_to_script>  # Imports specified markdown script
"""
import json
import re
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "settings.json"


def parse_fast_batch_sections(content: str):
    """Parse scenes from the 'Fast Batch Copy' sections if present."""
    pairs = []
    
    # 1. Extract Image Prompts from batch copy
    img_prompts = []
    vid_prompts = []
    
    # Look for Fast Batch Copy: All Image Prompts
    img_section_match = re.search(
        r"##.*?All Image Prompts.*?(?:```(?:text)?\s*)(.*?)(?:```)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if img_section_match:
        raw_text = img_section_match.group(1).strip()
        # Split by === SCENE X ... ===
        scenes = re.split(r"===\s*SCENE\s*\d+[^=\n]*===", raw_text)
        img_prompts = [s.strip() for s in scenes if s.strip()]

    # Look for Fast Batch Copy: All Video Motion Prompts
    vid_section_match = re.search(
        r"##.*?All Video Motion Prompts.*?(?:```(?:text)?\s*)(.*?)(?:```)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if vid_section_match:
        raw_text = vid_section_match.group(1).strip()
        scenes = re.split(r"===\s*SCENE\s*\d+[^=\n]*===", raw_text)
        vid_prompts = [s.strip() for s in scenes if s.strip()]

    if img_prompts and vid_prompts:
        count = min(len(img_prompts), len(vid_prompts))
        for i in range(count):
            pairs.append((img_prompts[i], vid_prompts[i]))

    return pairs


def parse_shot_by_shot_sections(content: str):
    """Parse scenes from 'Detailed Shot-by-Shot Production Breakdown'."""
    pairs = []
    # Split by shots: ### Shot 1: ...
    shot_blocks = re.split(r"###\s*Shot\s*\d+[:\s]", content, flags=re.IGNORECASE)
    for block in shot_blocks[1:]:  # skip before first shot
        # Find Step 1 Image Prompt
        img_match = re.search(
            r"(?:Step\s*1:.*?Image Prompt:.*?```(?:text)?\s*)(.*?)(?:```)",
            block,
            re.DOTALL | re.IGNORECASE,
        )
        # Find Step 2 Video Motion Prompt
        vid_match = re.search(
            r"(?:Step\s*2:.*?Video Motion Prompt:.*?```(?:text)?\s*)(.*?)(?:```)",
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if img_match and vid_match:
            img_p = img_match.group(1).strip()
            vid_p = vid_match.group(1).strip()
            pairs.append((img_p, vid_p))

    return pairs


def parse_generic_markdown(content: str):
    """Fallback: look for paired image and video prompt markers anywhere in content."""
    pairs = []
    # Match patterns like:
    # Image Prompt: ...
    # Video Prompt: ...
    pattern = re.compile(
        r"(?:Image\s*Prompt:?\s*)(?:```(?:text)?\s*)?(.*?)(?:```|\n\s*\*(?:\s*\*\*Video|\n\s*Video)|$)"
        r".*?"
        r"(?:Video(?:\s*Motion)?\s*Prompt:?\s*)(?:```(?:text)?\s*)?(.*?)(?:```|\n\s*---|\n\s*###|$)",
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(content):
        img_p = match.group(1).strip()
        vid_p = match.group(2).strip()
        if img_p and vid_p:
            pairs.append((img_p, vid_p))
    return pairs


def parse_script_file(filepath: Path | str):
    """Extract prompt pairs from a markdown script file."""
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"Script file not found: {p}")
    
    content = p.read_text(encoding="utf-8")
    
    # Try Fast Batch Copy sections first
    pairs = parse_fast_batch_sections(content)
    if pairs:
        return pairs

    # Try Shot-by-Shot breakdown
    pairs = parse_shot_by_shot_sections(content)
    if pairs:
        return pairs

    # Fallback to generic parsing
    pairs = parse_generic_markdown(content)
    return pairs


def import_script_to_settings(script_path: Path | str, settings_path: Path | str = SETTINGS_FILE, limit: int = None):
    """Parse script file and save pairs into settings.json."""
    script_p = Path(script_path)
    settings_p = Path(settings_path)
    
    pairs = parse_script_file(script_p)
    if not pairs:
        raise ValueError(f"No prompt pairs could be found in {script_p.name}")

    if limit and limit > 0:
        pairs = pairs[:limit]

    saved = {}
    if settings_p.exists():
        try:
            saved = json.loads(settings_p.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Save pairs as list of [img, vid]
    saved["pairs"] = [list(pair) for pair in pairs]
    settings_p.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return pairs


def main():
    target_file = None
    limit = 8  # Default to 8 pairs (leave out 9th) as requested

    args = sys.argv[1:]
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg in ("--limit", "-n", "-l") and idx + 1 < len(args):
            try:
                limit = int(args[idx + 1])
            except ValueError:
                pass
            idx += 2
        elif arg.isdigit():
            limit = int(arg)
            idx += 1
        elif not target_file:
            target_file = Path(arg)
            idx += 1
        else:
            idx += 1

    if not target_file:
        # Default to brandy-script.md or find any .md in current directory
        candidates = [
            APP_DIR / "brandy-script.md",
            *APP_DIR.glob("*.md"),
        ]
        for c in candidates:
            if c.exists() and c.name.lower() != "readme.md":
                target_file = c
                break

    if not target_file or not target_file.exists():
        print("❌ Error: No script markdown file found.")
        print("Usage: python import_script.py [path_to_script.md] [--limit 8]")
        sys.exit(1)

    print(f"📖 Reading and analyzing script: {target_file.name} (limit={limit})...")
    try:
        pairs = import_script_to_settings(target_file, SETTINGS_FILE, limit=limit)
        print(f"✅ Successfully extracted {len(pairs)} prompt pair(s) (1 to {len(pairs)}) and saved to settings.json!\n")
        for i, (img, vid) in enumerate(pairs, 1):
            img_snippet = (img[:75] + "...") if len(img) > 75 else img
            vid_snippet = (vid[:75] + "...") if len(vid) > 75 else vid
            print(f"Pair #{i}:")
            print(f"  📸 Image : {img_snippet}")
            print(f"  🎬 Video : {vid_snippet}")
        print("\n🚀 You can now run the automation in the app (`python app.py`).")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
