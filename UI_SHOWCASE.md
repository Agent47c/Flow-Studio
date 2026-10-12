# Flow Studio — Visual Design & Interface Showcase

> **Executive Review & Sign-Off Document**  
> **Suite:** Flow Studio Autonomous Image-to-Video Engine (Revision 3)  
> **Platform:** Windows Desktop Application (CustomTkinter + Playwright Engine)  
> **Status:** Feature Complete & Production Hardened  

---

## 📋 Document Overview

This showcase presents the complete visual interface and UX architecture of **Flow Studio**. It has been compiled for team review and design approval before further autonomous workflow expansion.

Flow Studio follows a unified, 3-column macOS/Apple Human Interface Pro aesthetic:
1. **Left Navigation Bar (240px):** Mode navigation with live badge counts, pipeline status, and real-time completion gauges.
2. **Main Workspace Canvas (Flexible):** Clean card-based views with zero clutter, high contrast typography, and contextual controls.
3. **Inspector Sidebar (340px):** Persistent live telemetry including active script metadata, Google Flow connection status, and batch queue indicators.

---

## 📑 Visual Index

- [1. Getting Started & Setup Wizard](#1-getting-started--setup-wizard)
- [2. Autonomous Run Dashboard (Active Batch)](#2-autonomous-run-dashboard-active-batch)
- [3. Policy Violation & Attention Handling](#3-policy-violation--attention-handling)
- [4. Problems & Errors Review Center](#4-problems--errors-review-center)
- [5. Scripts & Prompt Engineering Pipeline](#5-scripts--prompt-engineering-pipeline)
- [6. Visual Calibration Controls Catalogue](#6-visual-calibration-controls-catalogue)
- [7. Engine Timing & Operating Settings](#7-engine-timing--operating-settings)
- [8. Real-Time Diagnostics & Live Logs](#8-real-time-diagnostics--live-logs)
- [9. Sleek Dark Mode Variant](#9-sleek-dark-mode-variant)
- [10. Design System Specifications](#10-design-system-specifications)

---

## 1. Getting Started & Setup Wizard

The **Setup Wizard** greets first-time users or unconfigured environments, providing a guided 4-step onboarding checklist to ensure zero-friction setup.

![01 Setup Wizard](docs/screenshots/01_setup_wizard.png)

### Key Features & Design Highlights
* **One-Click Step Guidance:** Clear progress steps (Install Playwright, Connect Google Flow, Load Scripts, Run First Batch).
* **Direct Interactive Triggers:** Deep links to launch the calibration check, test connection, or open the target script directory.
* **Persistent Connection Badge:** Instant visual feedback confirming whether Google Flow's session cookies and browser profiles are intact.

---

## 2. Autonomous Run Dashboard (Active Batch)

The central operational hub where autonomous video generation executes. Designed to give users complete peace of mind while running unattended for hours.

![02 Run Active Batch](docs/screenshots/02_run_active_batch.png)

### Key Features & Design Highlights
* **Hero Status Card:** High-visibility active pair indicator (`Pair 2 of 8`), overall progress bar (35%), elapsed run time, and real-time failure counters.
* **Live Pipeline Visualizer:** Multi-stage workflow tracks (`Image Prompt Entered` ➔ `Image Generating` ➔ `Video Prompt Queued` ➔ `Saved to Disk`) with animated status beacons.
* **Non-Destructive Pause & Stop:** Dedicated emergency controls allowing the user to gracefully pause or stop generation without losing state or burning generation tokens.
* **Right Context Inspector:** Live breakdown of active script (`scotchgard-script.md`), estimated time remaining, and canvas tile counts.

---

## 3. Policy Violation & Attention Handling

Google Flow's AI safety guardrails occasionally trigger policy violations or content rejections. Flow Studio detects these immediately without crashing or freezing.

![03 Run Attention Banner](docs/screenshots/03_run_attention_banner.png)

### Key Features & Design Highlights
* **High-Priority Red Attention Banner:** Prominently alerts the user when an unexpected modal, policy rejection, or DOM stall occurs.
* **Instant Triage Actions:** Direct buttons to **Dismiss & Skip**, **Retry Pair**, or **Inspect Problem** directly from the run canvas.
* **Automatic Token Protection:** Never loops infinitely on blocked prompts—records the failure reason and safely moves forward.

---

## 4. Problems & Errors Review Center

The dedicated triage hub where all failures, timeouts, and policy rejections are cataloged for inspection and single-click reprocessing.

![04 Problems Errors](docs/screenshots/04_problems_errors.png)

### Key Features & Design Highlights
* **Detailed Problem Cards:** Displays the script name, exact pair index, error type (e.g., `Policy Rejection: Harmful content filter triggered`), and timestamp.
* **Inspector & Replay Controls:** 
  * `Inspect Prompts`: Review the exact text that caused the violation.
  * `Replay Pair`: Re-inject the pair directly into the active run queue after prompt modification.
  * `Clear`: Safely dismiss resolved items.
* **Sidebar Badge Counter:** Dynamic red pill indicator in the sidebar alerts users whenever unattended errors occur.

---

## 5. Scripts & Prompt Engineering Pipeline

Flow Studio's built-in markdown script importer and prompt pair reviewer. Handles batch ingestion of full video production packages.

![05 Scripts Prompts](docs/screenshots/05_scripts_prompts.png)

### Key Features & Design Highlights
* **Automated Package Parser:** Automatically extracts scene numbers, image generation prompts, and Veo video motion instructions from Markdown packages.
* **Side-by-Side Prompt Review:** View and edit image prompt / video motion prompt pairs directly within clean structured cards.
* **Batch Queue Management:** Seamlessly load multiple scripts into the queue with auto-advancing logic once each batch finishes.

---

## 6. Visual Calibration Controls Catalogue

Calibration provides interactive testing tools to verify that every DOM selector and interactive element on Google Flow is functional.

![06 Calibrate Controls](docs/screenshots/06_calibrate_controls.png)

### Key Features & Design Highlights
* **9-Element Diagnostic Grid:** Verifies Prompts Inputs, Generate Buttons, Mode Switchers, Canvas Tiles, Resolution Selectors, and Video Download Anchors.
* **Instant Green/Red Health Status:** Instant visual confirmation of selector validity against Google's live Web UI updates.
* **Interactive Testing Action:** Single-click `Test Element` buttons trigger safe non-destructive Playwright locator probes.

---

## 7. Engine Timing & Operating Settings

Comprehensive configuration panel governing timeout intervals, human-like delays, retry limits, and filesystem destinations.

![07 Settings](docs/screenshots/07_settings.png)

### Key Features & Design Highlights
* **Timeout & Delay Governance:** Configurable image wait timeout (default 120s), video generation timeout (default 360s), and human jitter pauses.
* **Policy Reject Action Policy:** Define automated behavior on rejections (`Skip Pair`, `Pause for User`, or `Auto-Retry`).
* **Path & Profile Controls:** Select headless or visible browser modes, specify custom Chrome profiles, and configure output directory targets.

---

## 8. Real-Time Diagnostics & Live Logs

A terminal-inspired live diagnostics stream designed for engineering oversight, debugging, and real-time execution tracking.

![08 Logs Diagnostics](docs/screenshots/08_logs_diagnostics.png)

### Key Features & Design Highlights
* **Monospace Terminal Feed:** Clean high-contrast console log with automatic timestamping and color-coded message severity (`[INFO]`, `[SUCCESS]`, `[WARN]`, `[ERROR]`).
* **Log Utilities:** Quick-action buttons to **Clear Stream**, **Copy All Logs**, or **Export Log File** to disk.
* **Log Level Filter:** Filter views between All Messages, Execution Warnings, or Critical Failures.

---

## 9. Sleek Dark Mode Variant

Flow Studio includes built-in auto, light, and dark appearance modes engineered with deep OLED contrast ratios.

![09 Dark Mode Run](docs/screenshots/09_dark_mode_run.png)

### Key Features & Design Highlights
* **Modern Pro Aesthetic:** Deep neutral zinc backgrounds (`#1c1c1e`), translucent sidebar surfaces (`#232326`), and vivid Apple system accents (`#0a84ff`).
* **Ergonomic Long-Session Comfort:** Reduces eye fatigue during multi-hour overnight video rendering runs.

---

## 10. Design System Specifications

| Token | Light Theme | Dark Theme | Purpose |
| :--- | :--- | :--- | :--- |
| **Window Background** | `#f5f5f7` | `#1c1c1e` | Main application shell background |
| **Sidebar Surface** | `#ececf0` | `#232326` | Navigation & persistent telemetry |
| **Card Surface** | `#ffffff` | `#2c2c2e` | Elevates actionable content blocks |
| **Primary Accent** | `#0071e3` | `#0a84ff` | Primary action buttons, active navigation, progress |
| **Success State** | `#248a3d` | `#30d158` | Completed generations & healthy connections |
| **Danger / Alert** | `#d70015` | `#ff453a` | Policy violations, fatal errors, stop buttons |
| **Warning State** | `#f59e0b` | `#fbbf24` | Retries, pauses, timeouts |
| **Border / Rule** | `#d2d2d7` | `#3a3a3d` | Clean card outlines and section dividers |

---

## 🚀 Sign-Off & Approval Summary

* **Visual Consistency:** Unified 3-column architecture across all 7 views.
* **Error Resilience:** Real-time attention banners and dedicated Problem center prevent unhandled lockups.
* **Non-Destructive Operations:** Independent background rendering engine ensures uninterrupted video generation.

*Prepared for executive stakeholder review and deployment sign-off.*
