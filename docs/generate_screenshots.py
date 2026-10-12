import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

DOCS_DIR = Path("docs")
SCREENSHOTS_DIR = DOCS_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
SHOWCASE_HTML = DOCS_DIR / "showcase.html"

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flow Studio — Visual Showcase</title>
<style>
:root{
  --bg:#e8e8ed;--win:#f5f5f7;--side:#ececf0;--card:#fff;--text:#1d1d1f;
  --sub:#6e6e73;--line:#d2d2d7;--fill:#f0f0f3;--acc:#0071e3;--accT:#fff;
  --ok:#248a3d;--bad:#d70015;--warn:#f59e0b;--shadow:0 20px 60px rgba(0,0,0,.15);
}
:root[data-theme="dark"]{
  --bg:#000;--win:#1c1c1e;--side:#232326;--card:#2c2c2e;--text:#f5f5f7;
  --sub:#a1a1a6;--line:#3a3a3d;--fill:#3a3a3c;--acc:#0a84ff;--ok:#30d158;
  --bad:#ff453a;--warn:#fbbf24;--shadow:0 20px 60px rgba(0,0,0,.6);
}
*{box-sizing:border-box}
body{
  margin:0;background:var(--bg);color:var(--text);
  font:13.5px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI Variable","Segoe UI",Inter,Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;padding:24px 20px;
}
button,input,select{font:inherit;color:inherit}
.win{
  max-width:1320px;margin:0 auto;background:var(--win);border-radius:14px;
  box-shadow:var(--shadow);overflow:hidden;border:1px solid var(--line);
}
.bar{
  display:flex;align-items:center;justify-content:space-between;
  padding:11px 18px;border-bottom:1px solid var(--line);background:var(--side);
}
.bar b{font-weight:700;font-size:14px;display:flex;align-items:center;gap:8px}
.bar b span{background:var(--acc);color:#fff;font-size:10.5px;padding:2px 7px;border-radius:6px;font-weight:600}
.seg{display:inline-flex;background:var(--fill);border-radius:8px;padding:2px}
.seg button{border:0;background:none;padding:4px 12px;border-radius:6px;cursor:pointer;color:var(--sub);font-size:12px;font-weight:500}
.seg button.on{background:var(--card);color:var(--text);box-shadow:0 1px 3px rgba(0,0,0,.12)}
.app{display:grid;grid-template-columns:240px 1fr 340px;min-height:740px}
.side{
  background:var(--side);border-right:1px solid var(--line);
  padding:18px 12px;display:flex;flex-direction:column;gap:4px;
}
.nav{
  display:flex;justify-content:space-between;align-items:center;width:100%;
  text-align:left;border:0;background:none;padding:9px 12px;border-radius:8px;
  cursor:pointer;color:var(--text);font-weight:600;font-size:13px;
}
.nav:hover{background:var(--fill)}
.nav.on{background:var(--acc);color:#fff}
.nav small{opacity:.7}
.nav .badge{
  font-size:10.5px;padding:1px 7px;border-radius:6px;font-weight:700;
}
.nav .badge.red{background:var(--bad);color:#fff}
.nav .badge.blue{background:rgba(0,113,227,.15);color:var(--acc)}
.nav.on .badge{background:rgba(255,255,255,.25);color:#fff}
.status{
  margin-top:auto;background:var(--card);border:1px solid var(--line);
  border-radius:12px;padding:14px;
}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--sub);font-weight:600}
.dot{width:8px;height:8px;border-radius:50%;background:var(--sub)}
.dot.ok{background:var(--ok);box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 25%,transparent)}
.dot.bad{background:var(--bad);box-shadow:0 0 0 3px color-mix(in srgb,var(--bad) 25%,transparent)}
.status strong{display:block;font-size:22px;font-weight:700;margin:6px 0 8px;letter-spacing:-.02em}
.track{height:6px;border-radius:3px;background:var(--fill);overflow:hidden}
.track i{display:block;height:100%;width:35%;background:var(--acc);border-radius:3px}
main{padding:26px 30px;min-width:0;overflow-y:auto;max-height:820px}
.view{display:none}.view.on{display:block}
.head{
  display:flex;justify-content:space-between;align-items:flex-start;
  gap:16px;flex-wrap:wrap;margin-bottom:20px;
}
h1{font-size:28px;font-weight:700;letter-spacing:-.025em;margin:0}
.head p{margin:4px 0 0;color:var(--sub);font-size:13px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.btn{
  border:0;border-radius:8px;padding:7px 14px;background:var(--fill);
  cursor:pointer;font-weight:600;font-size:12.5px;color:var(--text);
  display:inline-flex;align-items:center;gap:6px;
}
.btn:hover{filter:brightness(.96)}
.btn.p{background:var(--acc);color:#fff}
.btn.d{color:var(--bad)}
.btn.s{background:var(--bad);color:#fff}
.btn[disabled]{opacity:.45;cursor:default}
.card{
  background:var(--card);border:1px solid var(--line);border-radius:14px;margin-bottom:16px;
}
.card>h2{font-size:13px;font-weight:700;margin:0;padding:14px 18px 0;color:var(--sub)}
.item{
  display:flex;justify-content:space-between;align-items:center;
  gap:16px;padding:14px 18px;border-top:1px solid var(--line);flex-wrap:wrap;
}
.card>h2+.item{border-top:0}
.item span.l{font-weight:600}.item small{display:block;color:var(--sub);font-weight:400;margin-top:2px}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:0}
.step{padding:18px;border-left:1px solid var(--line)}
.step:first-child{border-left:0}
.step .n{
  width:24px;height:24px;border-radius:50%;background:var(--fill);
  display:grid;place-items:center;font-size:12px;font-weight:700;margin-bottom:10px;
}
.step.done .n{background:var(--ok);color:#fff}
.step p{margin:0 0 10px;color:var(--sub);font-size:12.5px}
input[type=text],input[type=number],select{
  background:var(--fill);border:1px solid transparent;border-radius:8px;
  padding:7px 11px;min-width:0;
}
input[type=text]{width:320px;max-width:100%}input[type=number]{width:84px}
.sw{
  appearance:none;width:42px;height:26px;border-radius:13px;
  background:var(--fill);border:1px solid var(--line);position:relative;
  cursor:pointer;flex:none;transition:.2s;
}
.sw::after{
  content:"";position:absolute;top:2px;left:2px;width:20px;height:20px;
  border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.3);transition:.2s;
}
.sw:checked{background:var(--ok);border-color:var(--ok)}.sw:checked::after{left:18px}
.pair{padding:16px 18px;border-top:1px solid var(--line)}
.pair:first-of-type{border-top:0}
.pair header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-weight:700}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.cols div{background:var(--fill);border-radius:10px;padding:10px 12px;font-size:12.5px}
.cols em{display:block;font-style:normal;color:var(--sub);font-size:11.5px;margin-bottom:4px;font-weight:600}
.cols p{margin:0;line-height:1.4}
.log{
  background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:16px;min-height:420px;font:12px/1.7 ui-monospace,"SF Mono",Consolas,monospace;
  overflow:auto;
}
.log div{display:flex;gap:10px;padding:1px 0}
.log .t{color:var(--sub);flex:none}
.log .tag{font-weight:700;padding:0 4px;border-radius:4px}
.log .tag.info{background:rgba(0,113,227,.15);color:var(--acc)}
.log .tag.ok{background:rgba(36,138,61,.15);color:var(--ok)}
.log .tag.err{background:rgba(215,0,21,.15);color:var(--bad)}
.log .tag.warn{background:rgba(245,158,11,.15);color:var(--warn)}
.insp{
  border-left:1px solid var(--line);background:var(--side);
  padding:24px 20px;display:flex;flex-direction:column;gap:14px;
}
.pc{
  background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px 10px;
}
.pc header{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.pc header>div{flex:1;min-width:0}
.pi{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;font-size:20px;background:var(--fill);flex:none}
.pc h3{font-size:12.5px;color:var(--sub);font-weight:600;margin:0}
.pc b{display:block;font-size:19px;font-weight:700;letter-spacing:-.02em;line-height:1.25}
.pc .r{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid var(--line);font-size:13px}
.pc .r span:last-child{color:var(--sub);text-align:right}
.now{padding:20px 22px}
.nowrow{display:flex;gap:18px;margin-top:16px}
.th{
  width:96px;height:140px;border-radius:12px;
  background:linear-gradient(160deg,#f6c177,#b5651d 60%,#3a2a1a);
  flex:none;display:grid;place-items:center;font-size:32px;
}
.th.e{background:var(--fill)}
.pipe{display:flex;gap:12px;margin-top:14px}
.stg{flex:1;background:var(--fill);border-radius:12px;padding:12px 14px}
.stg small{display:block;color:var(--sub);font-size:11.5px;font-weight:600}
.stg b{display:flex;align-items:center;gap:8px;font-weight:700;font-size:13.5px;margin-top:2px}
.stg.work{box-shadow:inset 0 0 0 2px var(--acc)}.stg.ok b{color:var(--ok)}.stg.err{box-shadow:inset 0 0 0 2px var(--bad)}.stg.err b{color:var(--bad)}
.banner{
  background:color-mix(in srgb,var(--bad) 10%,var(--card));
  border:1px solid color-mix(in srgb,var(--bad) 40%,transparent);
  border-radius:12px;padding:14px 16px;margin-top:16px;
}
.banner p{margin:4px 0 12px;font-size:12.5px;color:var(--text)}
.chip{
  font-size:11px;font-weight:700;padding:3px 9px;border-radius:8px;
  background:var(--fill);color:var(--sub);white-space:nowrap;
}
.chip.ok{color:var(--ok);background:color-mix(in srgb,var(--ok) 14%,transparent)}
.chip.work{color:var(--acc);background:color-mix(in srgb,var(--acc) 14%,transparent)}
.chip.err{color:var(--bad);background:color-mix(in srgb,var(--bad) 14%,transparent)}
.pr{display:flex;align-items:center;gap:12px;padding:11px 18px;border-top:1px solid var(--line)}
.card>h2+.pr{border-top:0}
.pr .n{width:22px;color:var(--sub);font-weight:700}
.pr .t{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500}
.spin{
  width:13px;height:13px;border:2px solid var(--line);
  border-top-color:var(--acc);border-radius:50%;animation:sp .8s linear infinite;
  display:inline-block;
}
@keyframes sp{to{transform:rotate(1turn)}}
.how{display:grid;grid-template-columns:repeat(3,1fr)}
.how div{padding:16px 18px;border-left:1px solid var(--line);font-size:12.5px;color:var(--sub)}
.how div:first-child{border-left:0}
.how b{display:block;color:var(--text);font-size:13.5px;margin-bottom:3px}
.path{font:12px ui-monospace,Consolas,monospace;background:var(--fill);padding:5px 9px;border-radius:6px}
.tbl{width:100%;border-collapse:collapse}
.tbl th{text-align:left;font-size:11.5px;color:var(--sub);padding:10px 18px;border-bottom:1px solid var(--line);font-weight:600}
.tbl td{padding:12px 18px;border-top:1px solid var(--line);font-size:12.5px}
.tbl tr:first-child td{border-top:0}
.tbl code{font:11.5px ui-monospace,Consolas,monospace;background:var(--fill);padding:3px 6px;border-radius:4px}
</style>
</head>
<body>
<div class="win" id="win">
  <div class="bar">
    <b>Flow Studio <span>Autonomous Batch Suite</span></b>
    <div class="seg" id="theme">
      <button data-t="light">Light</button>
      <button data-t="auto" class="on">Auto</button>
      <button data-t="dark">Dark</button>
    </div>
  </div>
  <div class="app">
    <aside class="side">
      <button class="nav" data-v="start">Setup <span class="badge blue">Ready</span></button>
      <button class="nav on" data-v="run">Run</button>
      <button class="nav" data-v="problems">Problems &amp; Errors <span class="badge red">1</span></button>
      <button class="nav" data-v="prompts">Scripts &amp; Prompts</button>
      <button class="nav" data-v="calibrate">Calibrate</button>
      <button class="nav" data-v="settings">Settings</button>
      <button class="nav" data-v="logs">Logs</button>

      <div class="status">
        <div class="pill"><span class="dot ok"></span> Running batch</div>
        <strong>2 of 8 videos</strong>
        <div class="track"><i></i></div>
        <small style="display:block;margin-top:8px;color:var(--sub)">Active: scotchgard-script.md</small>
      </div>
    </aside>

    <main>
      <!-- 1. SETUP VIEW -->
      <section class="view" id="start">
        <div class="head">
          <div>
            <h1>Getting Started</h1>
            <p>Complete these 3 simple steps once to pair Flow Studio with your Google Flow workspace.</p>
          </div>
          <div class="row">
            <button class="btn p">Re-run setup wizard</button>
          </div>
        </div>

        <div class="card">
          <h2>Setup checklist</h2>
          <div class="steps">
            <div class="step done">
              <div class="n">✓</div>
              <strong style="display:block;font-size:13.5px;margin-bottom:2px">1. Sign in</strong>
              <p>Sign in to your Google Account inside the dedicated profile.</p>
              <button class="btn" style="width:100%">Open browser</button>
            </div>
            <div class="step done">
              <div class="n">✓</div>
              <strong style="display:block;font-size:13.5px;margin-bottom:2px">2. Project URL</strong>
              <p>Set your destination Google Flow project workspace URL.</p>
              <button class="btn" style="width:100%">Change project</button>
            </div>
            <div class="step done">
              <div class="n">✓</div>
              <strong style="display:block;font-size:13.5px;margin-bottom:2px">3. Calibrate</strong>
              <p>Map the 9 UI buttons and prompt inputs on Google Flow.</p>
              <button class="btn" style="width:100%">Calibrate all</button>
            </div>
          </div>
        </div>

        <div class="card">
          <h2>Configuration status</h2>
          <div class="item">
            <div><span class="l">Google Flow Session</span><small>Connected · Profile saved in chrome_profile/</small></div>
            <span class="chip ok">✓ Signed in</span>
          </div>
          <div class="item">
            <div><span class="l">Project Workspace</span><small>https://flow.google.com/project/52744cb5-fc9f-461d-b064-fa51c2f63653</small></div>
            <span class="chip ok">✓ Validated</span>
          </div>
          <div class="item">
            <div><span class="l">DOM Interface Selectors</span><small>All 9 selectors mapped cleanly in selectors.json</small></div>
            <span class="chip ok">✓ 9 / 9 Mapped</span>
          </div>
        </div>
      </section>

      <!-- 2. RUN VIEW (ACTIVE BATCH) -->
      <section class="view on" id="run">
        <div class="head">
          <div>
            <h1>Run</h1>
            <p>scotchgard-script.md · 8 pairs. Each pair makes an image, then a video.</p>
          </div>
          <div class="row">
            <button class="btn d">⏹ Stop</button>
            <button class="btn">Restart from #1</button>
            <button class="btn p" disabled>▶ Start batch</button>
          </div>
        </div>

        <div class="card now">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div class="pill"><span class="dot ok"></span> Running</div>
            <small style="color:var(--sub)">scotchgard-script.md</small>
          </div>
          <strong style="display:block;font-size:32px;margin:8px 0 10px;letter-spacing:-.025em">2 of 8 videos</strong>
          <div class="track" style="margin-bottom:18px"><i style="width:30%"></i></div>

          <div class="nowrow">
            <div class="th">🎬</div>
            <div style="flex:1;min-width:0">
              <div style="color:var(--sub);font-size:12px;font-weight:600">Pair 2 of 8 · Laboratory Splash</div>
              <p style="margin:4px 0 12px;font-size:13px;line-height:1.4">Cinematic dynamic low-angle shot in 9:16 vertical orientation of a clear glass laboratory flask slipping and shattering against a black slate bench…</p>
              
              <div class="pipe">
                <div class="stg ok">
                  <small>1 · Image</small>
                  <b>✓ Done</b>
                </div>
                <div class="stg work">
                  <small>2 · Video</small>
                  <b><span class="spin"></span> Generating (42%)</b>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="card">
          <h2>All pairs</h2>
          <div class="pr">
            <span class="n">1</span>
            <span class="t">Chemist Adjusting Brass Valves Reaction</span>
            <span class="chip ok">✓ Done</span>
          </div>
          <div class="pr">
            <span class="n">2</span>
            <span class="t">Laboratory Flask Shattering on Slate Bench</span>
            <span class="chip work"><span class="spin"></span> Video 42%</span>
          </div>
          <div class="pr">
            <span class="n">3</span>
            <span class="t">Macro Splash on White Canvas Sneaker</span>
            <span class="chip">Waiting</span>
          </div>
          <div class="pr">
            <span class="n">4</span>
            <span class="t">Chemist Scrubbing Sneaker with Turpentine</span>
            <span class="chip">Waiting</span>
          </div>
          <div class="pr">
            <span class="n">5</span>
            <span class="t">Split-Focus Grime vs Pristine Clean Canvas</span>
            <span class="chip">Waiting</span>
          </div>
          <div class="pr">
            <span class="n">6</span>
            <span class="t">Extreme Macro Droplets Beading on Fabric</span>
            <span class="chip">Waiting</span>
          </div>
          <div class="pr">
            <span class="n">7</span>
            <span class="t">Chemist Spraying Aerosol on Textile Swatches</span>
            <span class="chip">Waiting</span>
          </div>
          <div class="pr">
            <span class="n">8</span>
            <span class="t">Punch Spills on Living Room Cream Sofa</span>
            <span class="chip">Waiting</span>
          </div>
        </div>

        <div class="card">
          <h2>Saved progress</h2>
          <div class="item">
            <div>
              <span class="l">scotchgard-script.md</span>
              <small>1 of 8 completed · Active in batch queue</small>
            </div>
            <div class="row">
              <button class="btn">Restart from #1</button>
            </div>
          </div>
        </div>
      </section>

      <!-- 3. RUN VIEW WITH ERROR BANNER (FOR DEMO) -->
      <section class="view" id="run-error">
        <div class="head">
          <div>
            <h1>Run · Needs Attention</h1>
            <p>scotchgard-script.md · Generation declined on Pair #2.</p>
          </div>
          <div class="row">
            <button class="btn">Restart from #1</button>
            <button class="btn p">▶ Resume batch</button>
          </div>
        </div>

        <div class="card now">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div class="pill"><span class="dot bad"></span> Needs your attention</div>
            <small style="color:var(--sub)">scotchgard-script.md</small>
          </div>
          <strong style="display:block;font-size:32px;margin:8px 0 10px;letter-spacing:-.025em">1 of 8 videos · 1 issue</strong>
          <div class="track" style="margin-bottom:18px"><i style="width:15%"></i></div>

          <div class="nowrow">
            <div class="th" style="background:#fee2e2;color:#b91c1c">✕</div>
            <div style="flex:1;min-width:0">
              <div style="color:var(--sub);font-size:12px;font-weight:600">Pair 2 of 8 · Laboratory Splash</div>
              <p style="margin:4px 0 12px;font-size:13px;line-height:1.4">Cinematic dynamic low-angle shot of chemical liquid shattering...</p>
              
              <div class="pipe">
                <div class="stg ok">
                  <small>1 · Image</small>
                  <b>✓ Done</b>
                </div>
                <div class="stg err">
                  <small>2 · Video</small>
                  <b>✕ Policy violation</b>
                </div>
              </div>

              <div class="banner">
                <strong style="color:var(--bad)">Policy violation on pair 2 (video)</strong>
                <p>Google Flow declined this video prompt: "The word 'shattering violently' was flagged by Google safety filters". Your progress is saved, so nothing is lost.</p>
                <div class="row">
                  <button class="btn p">Retry</button>
                  <button class="btn">Edit prompt</button>
                  <button class="btn">Skip pair</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 4. PROBLEMS & ERRORS VIEW -->
      <section class="view" id="problems">
        <div class="head">
          <div>
            <h1>Problems &amp; Errors</h1>
            <p>Review scripts with failed prompt pairs, safety flags, or timeouts, and replay or edit them.</p>
          </div>
          <div class="row">
            <button class="btn">🔄 Refresh</button>
            <button class="btn d">Clear Resolved</button>
          </div>
        </div>

        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;padding:16px 18px">
            <div style="display:flex;align-items:center;gap:10px">
              <strong style="font-size:15px">safety-pin-script.md</strong>
              <span class="chip err">1 failed pair</span>
              <small style="color:var(--sub)">Logged: Today at 14:11</small>
            </div>
            <div class="row">
              <button class="btn">📂 Edit in Prompts</button>
              <button class="btn p">▶ Replay Script</button>
              <button class="btn">⏭ Skip Script</button>
              <button class="btn d">✕ Clear</button>
            </div>
          </div>

          <div style="padding:0 18px 18px">
            <div style="background:var(--fill);border-radius:10px;padding:12px 14px">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <div style="display:flex;align-items:center;gap:8px">
                  <strong>Pair #1</strong>
                  <span class="chip err" style="font-size:10px">IMAGE STAGE</span>
                </div>
                <div class="row">
                  <button class="btn" style="padding:4px 10px;font-size:11.5px">🔍 Inspect &amp; Edit</button>
                  <button class="btn p" style="padding:4px 10px;font-size:11.5px">▶ Replay this Pair</button>
                </div>
              </div>
              <div style="color:var(--bad);font-weight:600;font-size:12px;margin-bottom:6px">
                Notice: Locator.wait_for: Timeout 30000ms exceeded while waiting for image generation canvas.
              </div>
              <div style="font-size:11.5px;color:var(--sub);line-height:1.4">
                <strong>Image:</strong> Cinematic close-up in 9:16 of an 1849 Edwardian inventor twisting a brass wire…<br>
                <strong>Video:</strong> Slow pan across the workbench as the spring snaps into shape…
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 5. SCRIPTS & PROMPTS VIEW -->
      <section class="view" id="prompts">
        <div class="head">
          <div>
            <h1>Scripts &amp; Prompts</h1>
            <p>Everything about what gets generated lives here.</p>
          </div>
          <div class="row">
            <button class="btn p">Add prompt pair</button>
            <button class="btn">Import .md script</button>
          </div>
        </div>

        <div class="card">
          <h2>How scripts work</h2>
          <div class="how">
            <div>
              <b>1. Add</b>
              Paste your .md script files into the scripts folder.
            </div>
            <div>
              <b>2. Choose</b>
              Pick the script to run below. Each has up to 8 pairs.
            </div>
            <div>
              <b>3. Run</b>
              Press Start batch. Finished scripts move to “completed”.
            </div>
          </div>
        </div>

        <div class="card">
          <h2>Scripts folder</h2>
          <div class="item">
            <div>
              <span class="l">Current queue folder</span>
              <small>Auto-detects markdown script files for autonomous sequential batching.</small>
            </div>
            <div class="row">
              <span class="path">scripts/</span>
              <button class="btn">Open folder</button>
            </div>
          </div>
          <div class="item">
            <div>
              <span class="l">Auto-advance queue</span>
              <small>When one script finishes, automatically load and start the next script in scripts/.</small>
            </div>
            <input type="checkbox" class="sw" checked>
          </div>
          <div class="item">
            <div>
              <span class="l">Move script when done</span>
              <small>Completed scripts move automatically to scripts/completed/ to protect tokens.</small>
            </div>
            <input type="checkbox" class="sw" checked>
          </div>
        </div>

        <div class="card">
          <h2>Active prompt pairs (scotchgard-script.md)</h2>
          <div class="pair">
            <header>Pair 1 of 8 · Chemist Adjusting Valves</header>
            <div class="cols">
              <div>
                <em>1. Image prompt</em>
                <p>Cinematic medium close-up in 9:16 vertical orientation inside a 1953 industrial laboratory. A 28-year-old female research chemist with tortoiseshell glasses adjusts brass valves…</p>
              </div>
              <div>
                <em>2. Video prompt</em>
                <p>[Image-to-Video] Starting from input keyframe image: Smooth slow forward push-in toward chemist. Synthetic fluid bubbles steadily inside glass tube with convection swirls…</p>
              </div>
            </div>
          </div>
          <div class="pair">
            <header>Pair 2 of 8 · Laboratory Splash</header>
            <div class="cols">
              <div>
                <em>1. Image prompt</em>
                <p>Cinematic dynamic low-angle shot in 9:16 vertical orientation of a clear glass laboratory flask slipping and shattering against a black slate bench…</p>
              </div>
              <div>
                <em>2. Video prompt</em>
                <p>[Image-to-Video] High-speed slow-motion capture. The flask fractures against slate counter, sending glass shards and clear droplets spraying downward…</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 6. CALIBRATE VIEW -->
      <section class="view" id="calibrate">
        <div class="head">
          <div>
            <h1>Calibrate Selectors &amp; Controls</h1>
            <p>Inspect and fine-tune every button, prompt box, and generation watcher on Google Flow.</p>
          </div>
          <div class="row">
            <button class="btn">Test All Selectors</button>
            <button class="btn p">Recalibrate All (9 Steps)</button>
          </div>
        </div>

        <div class="card">
          <h2>Full interface controls catalogue</h2>
          <table class="tbl">
            <thead>
              <tr>
                <th>Step #</th>
                <th>Interface Control</th>
                <th>Active Selector (selectors.json)</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><b>1</b></td>
                <td><b>Prompt Input Box</b></td>
                <td><code>div.ProseMirror</code></td>
                <td><span class="chip ok">✓ Calibrated</span></td>
                <td><button class="btn" style="padding:4px 10px;font-size:11.5px">Recalibrate</button></td>
              </tr>
              <tr>
                <td><b>2</b></td>
                <td><b>Image Generate Button</b></td>
                <td><code>button[aria-label="Start generation"]</code></td>
                <td><span class="chip ok">✓ Calibrated</span></td>
                <td><button class="btn" style="padding:4px 10px;font-size:11.5px">Recalibrate</button></td>
              </tr>
              <tr>
                <td><b>3</b></td>
                <td><b>Image Result Tile</b></td>
                <td><code>img.image</code></td>
                <td><span class="chip ok">✓ Calibrated</span></td>
                <td><button class="btn" style="padding:4px 10px;font-size:11.5px">Recalibrate</button></td>
              </tr>
              <tr>
                <td><b>4</b></td>
                <td><b>Card Options Hotbar (3-Dots)</b></td>
                <td><code>flow-image-hotbar button:nth-of-type(3)</code></td>
                <td><span class="chip ok">✓ Calibrated</span></td>
                <td><button class="btn" style="padding:4px 10px;font-size:11.5px">Recalibrate</button></td>
              </tr>
              <tr>
                <td><b>5</b></td>
                <td><b>Add to Prompt Menu Item</b></td>
                <td><code>button:has-text("Add to prompt")</code></td>
                <td><span class="chip ok">✓ Calibrated</span></td>
                <td><button class="btn" style="padding:4px 10px;font-size:11.5px">Recalibrate</button></td>
              </tr>
              <tr>
                <td><b>6</b></td>
                <td><b>Video Prompt Box</b></td>
                <td><code>div.ProseMirror</code></td>
                <td><span class="chip ok">✓ Calibrated</span></td>
                <td><button class="btn" style="padding:4px 10px;font-size:11.5px">Recalibrate</button></td>
              </tr>
              <tr>
                <td><b>7</b></td>
                <td><b>Video Generate Button</b></td>
                <td><code>button[aria-label="Start generation"]</code></td>
                <td><span class="chip ok">✓ Calibrated</span></td>
                <td><button class="btn" style="padding:4px 10px;font-size:11.5px">Recalibrate</button></td>
              </tr>
              <tr>
                <td><b>8</b></td>
                <td><b>Video Result Thumbnail</b></td>
                <td><code>img.thumbnail</code></td>
                <td><span class="chip ok">✓ Calibrated</span></td>
                <td><button class="btn" style="padding:4px 10px;font-size:11.5px">Recalibrate</button></td>
              </tr>
              <tr>
                <td><b>9</b></td>
                <td><b>Project More Options</b></td>
                <td><code>flow-more-options-menu &gt; button</code></td>
                <td><span class="chip ok">✓ Calibrated</span></td>
                <td><button class="btn" style="padding:4px 10px;font-size:11.5px">Recalibrate</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 7. SETTINGS VIEW -->
      <section class="view" id="settings">
        <div class="head">
          <div>
            <h1>Settings</h1>
            <p>Customize timeouts, delays, batch safety behavior, and visual appearance.</p>
          </div>
          <div class="row">
            <button class="btn p">Save Settings</button>
          </div>
        </div>

        <div class="card">
          <h2>Google Flow connection</h2>
          <div class="item">
            <div>
              <span class="l">Project workspace URL</span>
              <small>Your active project workspace where generated video cards will appear.</small>
            </div>
            <input type="text" value="https://flow.google.com/project/52744cb5-fc9f-461d-b064-fa51c2f63653">
          </div>
          <div class="item">
            <div>
              <span class="l">Show browser window</span>
              <small>Keep visible so you can watch progress and solve any Google CAPTCHAs.</small>
            </div>
            <input type="checkbox" class="sw" checked>
          </div>
        </div>

        <div class="card">
          <h2>Generation timing &amp; timeouts</h2>
          <div class="item">
            <div>
              <span class="l">Image generation timeout</span>
              <small>Max seconds to wait for Google Flow to render the base image tile.</small>
            </div>
            <div class="row"><input type="number" value="120"> <span style="color:var(--sub)">sec</span></div>
          </div>
          <div class="item">
            <div>
              <span class="l">Video generation timeout</span>
              <small>Max seconds to wait for Google Flow to finish rendering the video.</small>
            </div>
            <div class="row"><input type="number" value="360"> <span style="color:var(--sub)">sec</span></div>
          </div>
          <div class="item">
            <div>
              <span class="l">Human pause between pairs</span>
              <small>Simulates natural cadence between subsequent generation batches.</small>
            </div>
            <div class="row"><input type="number" value="5"> <span style="color:var(--sub)">sec</span></div>
          </div>
        </div>

        <div class="card">
          <h2>Recovery &amp; Safety behavior</h2>
          <div class="item">
            <div>
              <span class="l">On prompt policy decline</span>
              <small>Action taken when Google Flow flags safety filters on a prompt.</small>
            </div>
            <select style="padding:6px 12px;border-radius:8px;background:var(--fill)">
              <option selected>Ask me (display banner)</option>
              <option>Skip pair immediately</option>
              <option>Stop batch</option>
            </select>
          </div>
          <div class="item">
            <div>
              <span class="l">Max retry attempts</span>
              <small>Automatic retry attempts if a network glitch or timeout occurs.</small>
            </div>
            <input type="number" value="2">
          </div>
        </div>
      </section>

      <!-- 8. LOGS VIEW -->
      <section class="view" id="logs">
        <div class="head">
          <div>
            <h1>Logs &amp; Diagnostics</h1>
            <p>Live terminal stream from the Playwright browser automation driver.</p>
          </div>
          <div class="row">
            <button class="btn">📋 Copy</button>
            <button class="btn">Clear</button>
            <button class="btn">Open logs folder</button>
          </div>
        </div>

        <div class="log">
          <div><span class="t">16:48:02</span> <span class="tag info">INFO</span> 📂 Loaded script 'scotchgard-script.md' (8 pairs). Output set to 'output\\scotchgard/'.</div>
          <div><span class="t">16:48:03</span> <span class="tag info">INFO</span> Launching Playwright Chromium (profile: chrome_profile)...</div>
          <div><span class="t">16:48:06</span> <span class="tag ok">OK</span> Browser launched. Navigating to project workspace...</div>
          <div><span class="t">16:48:09</span> <span class="tag ok">OK</span> Google Flow canvas ready. Total tiles detected: 40.</div>
          <div><span class="t">16:48:10</span> <span class="tag info">INFO</span> =======================================================</div>
          <div><span class="t">16:48:10</span> <span class="tag info">INFO</span> 🎬 PROCESSING SCRIPT: scotchgard-script.md · Target: 8 prompt pairs</div>
          <div><span class="t">16:48:10</span> <span class="tag info">INFO</span> =======================================================</div>
          <div><span class="t">16:48:12</span> <span class="tag info">INFO</span> [1] entering image prompt...</div>
          <div><span class="t">16:48:14</span> <span class="tag info">INFO</span> [1] prompt entered, clicking generate</div>
          <div><span class="t">16:48:17</span> <span class="tag info">INFO</span>    watching selector: img.image (count before=40)</div>
          <div><span class="t">16:48:45</span> <span class="tag ok">OK</span>    ✓ image completed! (count 40→41, took 31s)</div>
          <div><span class="t">16:48:46</span> <span class="tag info">INFO</span> [1] selecting video mode...</div>
          <div><span class="t">16:48:49</span> <span class="tag info">INFO</span> [1] video prompt entered, clicking generate</div>
          <div><span class="t">16:49:15</span> <span class="tag ok">OK</span> [1] video progress: 54% (26s elapsed)</div>
          <div><span class="t">16:49:38</span> <span class="tag ok">OK</span> [1] ✓ Video #1 generated and verified on Google Flow canvas!</div>
          <div><span class="t">16:49:43</span> <span class="tag info">INFO</span> [2] entering image prompt...</div>
          <div><span class="t">16:49:45</span> <span class="tag info">INFO</span> [2] prompt entered, clicking generate</div>
          <div><span class="t">16:50:20</span> <span class="tag ok">OK</span>    ✓ image completed! (took 35s)</div>
          <div><span class="t">16:50:23</span> <span class="tag info">INFO</span> [2] video prompt entered, clicking generate</div>
          <div><span class="t">16:50:41</span> <span class="tag ok">OK</span> [2] video progress: 42% (18s elapsed)...</div>
        </div>
      </section>
    </main>

    <!-- RIGHT INSPECTOR OVERVIEW PANEL -->
    <aside class="insp">
      <div class="pc">
        <header>
          <div class="pi">🎬</div>
          <div>
            <h3>Active script</h3>
            <b style="font-size:16px;word-break:break-all">scotchgard-script.md</b>
          </div>
        </header>
        <div class="r"><span>Status</span><span style="color:var(--ok);font-weight:700">Running</span></div>
        <div class="r"><span>Pair progress</span><b>Pair 2 of 8</b></div>
        <div class="r"><span>Completed</span><b>1 video</b></div>
        <div class="r"><span>Estimated time</span><span>~4 min remaining</span></div>
      </div>

      <div class="pc">
        <header>
          <div class="pi">🌐</div>
          <div>
            <h3>Workspace</h3>
            <b>Google Flow</b>
          </div>
        </header>
        <div class="r"><span>Connection</span><span style="color:var(--ok);font-weight:700">Connected</span></div>
        <div class="r"><span>Profile</span><span>chrome_profile</span></div>
        <div class="r"><span>Canvas tiles</span><span>41 tiles</span></div>
      </div>

      <div class="pc">
        <header>
          <div class="pi">📦</div>
          <div>
            <h3>Batch queue</h3>
            <b>1 pending script</b>
          </div>
        </header>
        <div class="r"><span>Next script</span><span>slinky-script.md</span></div>
        <div class="r"><span>Auto-advance</span><span>Enabled</span></div>
      </div>
    </aside>
  </div>
</div>

<script>
function showView(vId, theme) {
  if (theme) {
    document.documentElement.setAttribute('data-theme', theme);
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
  document.querySelectorAll('.view').forEach(v => v.classList.remove('on'));
  document.querySelectorAll('.nav').forEach(n => {
    n.classList.remove('on');
    if (n.dataset.v === vId || (vId === 'run-error' && n.dataset.v === 'run')) {
      n.classList.add('on');
    }
  });
  const el = document.getElementById(vId);
  if (el) el.classList.add('on');
}
</script>
</body>
</html>
"""

SHOWCASE_HTML.write_text(HTML_CONTENT, encoding="utf-8")
print(f"Created showcase HTML: {SHOWCASE_HTML}")

# Generate high-resolution screenshots with Playwright
views_to_capture = [
    ("start", None, "01_setup_wizard.png", "Getting Started / Setup Wizard View"),
    ("run", None, "02_run_active_batch.png", "Autonomous Run View (Active Batch & Pipeline)"),
    ("run-error", None, "03_run_attention_banner.png", "Run View with Policy Violation Banner & Actions"),
    ("problems", None, "04_problems_errors.png", "Problems & Errors View (Inspect, Replay, Clear)"),
    ("prompts", None, "05_scripts_prompts.png", "Scripts & Prompts View (Guide, Queue, Pairs)"),
    ("calibrate", None, "06_calibrate_controls.png", "Calibrate View (9-Element Controls Catalogue)"),
    ("settings", None, "07_settings.png", "Settings View (Timing, Delays, Error Handling)"),
    ("logs", None, "08_logs_diagnostics.png", "Logs & Diagnostics View (Live Console & Stream)"),
    ("run", "dark", "09_dark_mode_run.png", "Dark Mode Variant (Sleek macOS Dark Theme)"),
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1400, "height": 920},
        device_scale_factor=2
    )
    page.goto(SHOWCASE_HTML.resolve().as_uri())
    page.wait_for_timeout(500)

    for vid, theme, filename, desc in views_to_capture:
        page.evaluate(f"showView('{vid}', '{theme or ''}')")
        page.wait_for_timeout(300)
        out_path = SCREENSHOTS_DIR / filename
        page.screenshot(path=str(out_path))
        print(f"Captured: {filename} ({desc})")

    browser.close()

print("\nALL SCREENSHOTS CAPTURED SUCCESSFULLY!")
