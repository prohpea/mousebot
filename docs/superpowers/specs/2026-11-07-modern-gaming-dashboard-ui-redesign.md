# Design Specification: Modern Gaming Dashboard UI Redesign

**Project:** CVM-colorBot v1.2.1  
**Author:** Antigravity Pairing Assistant  
**Date:** 2026-11-07  
**Status:** Approved by Builder Check & Ready for Implementation  

---

## 1. Context & Motivation

CVM-colorBot is a high-performance color aim assistance utility featuring real-time OBS UDP streaming (< 1ms latency), native TurboJPEG decoding, hardware mouse input (Serial, Arduino, KMBox, Ferrum), and humanized WindMouse bezier trajectory curves.

### Current Problems
1. **Sidebar Clutter & Bottleneck:** A narrow 195px sidebar attempts to host telemetry stats, hardware connection status, an oversized start/stop button, settings button, theme toggles, and navigation buttons. Text is frequently clipped (`...`).
2. **Infinite Single-Column Scrolling:** Sliders and switches are laid out in a single vertical column stretching thousands of pixels. Users must repeatedly scroll up and down to tweak related aimbot settings (e.g., FOV vs. X/Y Speeds vs. WindMouse).
3. **Weak Visual Hierarchy:** High-priority gameplay parameters (activation key, FOV radius, burst speeds) look identical to secondary debug parameters.
4. **Lack of Vietnamese Localization:** The user base and documentation (`HUONG_DAN_CAI_DAT.txt`) are Vietnamese, yet the tool currently only has English (`en.json`) and Chinese (`zh-CN.json`).

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **Modern 2-Column Card Grid:** Reorganize controls into clean, rounded cards (`corner_radius=10`, surface `#141822`, border `#232b3b`, accent emerald `#10b981` & cyan `#06b6d4`), cutting vertical scrolling by >50%.
- **Streamlined Header with Live Status Pills:** Relocate telemetry to the title bar/header (`OBS UDP: 120 FPS`, `Delay: 0.6ms`, `COM3: 4M Baud`), freeing the sidebar.
- **Dedicated, Readable Sidebar:** 
  - Prominent `START / STOP ENGINE` action button with glowing visual state.
  - Clean icons and navigation items:
    - `🎯 Combat (Main & Sec Aimbot)`
    - `👁️ Vision & Color (HSV Tuning)`
    - `⚡ Hardware & Stream (Serial / KMBox / OBS UDP)`
    - `📁 Profiles & Config (Burst & Spray presets)`
    - `📊 Telemetry & Debug (Live mouse & logs)`
  - Active profile quick card (`config.burst_spray.json`).
- **Vietnamese Language Support:** Add `locales/vi.json` with intuitive gaming terminology (e.g., "Phím kích hoạt", "Vùng quét FOV", "Đường chuột WindMouse", "Khử giật sấy Y-Decouple").
- **Preserve 100% Functionality:** Maintain exact config schema, hardware backends, threading, and hotkey bindings.

### Non-Goals
- Changing the underlying aimbot algorithms (`WindMouse.py`, `normal.py`, `OBS_UDP.py`).
- Migrating to a different GUI framework (remains 100% native `CustomTkinter`).

### Anti-Goals
- Breaking existing user configuration files (`config.json`, `config.burst_spray.json`).
- Adding external heavy dependencies or complex web engines.
- Introducing UI thread lockups during high-FPS frame capture.

---

## 3. Approaches Considered

1. **Approach 1: Modern Gaming Dashboard (2-Column Card Grid) — SELECTED**
   - Combines a streamlined left sidebar, header telemetry pills, and 2-column card grouping for Combat, Vision, and Hardware.
   - Selected for best readability, least eye fatigue, and optimal in-game usability.
2. **Approach 2: Ultra-Compact HUD**
   - Horizontal top tabs with ~750px minimal footprint.
   - *Trade-off:* Too tight for advanced settings (requires hiding sliders in nested accordions).
3. **Approach 3: Minimalist Obsidian Dark (1-Column Reskin)**
   - Keeps single-column vertical layout, only recoloring assets.
   - *Trade-off:* Does not solve the core pain point of infinite scrolling and cluttered sidebar.

---

## 4. UI Architecture & Component Specifications

### 4.1 Window & Title Bar
- **Dimensions:** 1020 x 680 (default geometry, resizable, minimum 960 x 620).
- **Custom Frameless Title Bar:**
  - Left: Logo icon + `CVM COLORBOT` label + version badge `v1.2.1`.
  - Center/Right: Live Telemetry Pills:
    - `[ 🟢 OBS UDP: 120 FPS ]`
    - `[ ⚡ Delay: 0.6 ms ]`
    - `[ 🔌 COM3: 4M Baud ]`
  - Far Right: Pro/Simple mode toggle, Minimize, Maximize, Close buttons.
  - *Pro/Simple Mode Behavior:* In Simple Mode, secondary/advanced cards (e.g., fine-grained WindMouse math and morphology filters) are tucked away, showing only essential targeting, speeds, color, and connection. In Pro Mode (default), all tuning cards are displayed.

### 4.2 Sidebar
- **Width:** 210px.
- **Top Section:**
  - Master Engine Button: Large `START ENGINE` (Emerald green `#10B981`, bold text, glowing hover) / `STOP ENGINE` (Crimson `#F43F5E`).
- **Navigation Menu:**
  - `🎯 Combat` (Sub-pills: Main Aimbot, Secondary Aimbot)
  - `👁️ Vision` (Target Color, HSV Calibration, Detection Filters)
  - `⚡ Hardware & Stream` (Mouse API, OBS UDP/NDI, Sens/DPI)
  - `📁 Profiles` (Profile management, Import/Export, Clipboard Auto-Import)
  - `📊 Telemetry & Debug` (Mouse click tester, System logs)
- **Bottom Section:**
  - Active Profile Card: Shows current config name (`config.burst_spray.json`) and audio toggle feedback status.
  - Theme / Language quick toggles.

### 4.3 Combat Tab (2-Column Card Grid)
- **Top Sub-Nav Pills:** `Main Aimbot` | `Secondary Aimbot`, plus Master Aimbot Switch.
- **Card 1: Target & FOV**
  - Aim Mode dropdown (`Normal / WindMouse`, `Flick`, `Silent`, `Bezier`, `PID`). Default: `Normal` (v1.2 WindMouse).
  - Activation Key bind button (`Right Mouse Button`, `Mouse 4`, etc.) with click-to-bind listener.
  - Activation Mode dropdown (`Giữ phím (Hold)` / `Bật/Tắt (Toggle)`).
  - FOV Slider (`10 - 150 px`, default `28 px`) with direct numeric entry.
  - Target Bone dropdown (`Đầu (Head)` / `Ngực (Neck/Chest)` / `Gần nhất (Closest)`).
  - Expandable ADS Row: ADS Key & ADS FOV toggle.
- **Card 2: Algorithm Parameters (WindMouse Humanizer for Normal Mode)**
  - When Mode is Normal:
    - Gravity Slider (`wm_gravity`: `1.0 - 20.0`, default `4.5`).
    - Wind Turbulence Slider (`wm_wind`: `0.0 - 10.0`, default `2.0`).
    - Max Step Slider (`wm_max_step`: `1.0 - 20.0 px`, default `8.0 px`).
    - Min Step Slider (`wm_min_step`: `0.1 - 5.0 px`, default `0.8 px`).
    - Delays & Distance Threshold (`wm_min_delay`, `wm_max_delay`, `wm_distance_threshold`).
  - When Mode is Flick / Silent / PID: Dynamically displays corresponding algorithm parameters.
- **Card 3: Speed & Recoil Spray Immunity**
  - X Speed Slider (`normal_x_speed`: `10 - 200%`, default `100%`).
  - Y Speed Slider (`normal_y_speed`: `10 - 200%`, default `70%`).
  - Y-Decouple Recoil Immunity Toggle switch (isolates horizontal tracking while spraying).
  - In-game Sensitivity & Mouse DPI inputs.
- **Card 4: Anti-Tremor & Reaction Timing**
  - Anti-tremor Deadband Slider (`0.0 - 5.0 px`, default `1.5 px`).
  - Human Reaction Time Sliders (`smooth_reaction_min`, `smooth_reaction_max`: `80ms - 200ms`).
  - Directional Flip Filter Toggle.
  - Audio Feedback Beep Toggle (sends UDP 4455 packet to PC 1 OBS).

### 4.4 Vision Tab
- **Card 1: Color Target Preset:** Selection (`yellow`, `purple`, `red`, `custom`).
- **Card 2: Custom HSV Calibration:**
  - Launch HSV Live Filter Preview button.
  - Min HSV Sliders (`Hue Min`, `Sat Min`, `Val Min`).
  - Max HSV Sliders (`Hue Max`, `Sat Max`, `Val Max`).
- **Card 3: Contour & Morphology Filters:**
  - Merge Distance slider (`detection_merge_distance`).
  - Min Contour Points slider (`detection_min_contour_points`).
  - Bounding Box Size & Aspect Ratio constraints.

### 4.5 Hardware & Capture Tab
- **Card 1: Hardware Mouse API:** Mode selector (Serial, Arduino, KMBox B+, KMBox Net, Ferrum, Medius), Port, Baud rate selector (with 4M Auto-Switch), Test Move button.
- **Card 2: Video Stream Capture:** Backend selector (OBS UDP, NDI, Capture Card, Desktop DDA), UDP Host/Port inputs, TurboJPEG acceleration status indicator.
- **Card 3: Input & Sensitivity Calibration:** Sens, DPI, Invert X/Y, Smoothing factors.

### 4.6 Profiles Tab
- Profile selector dropdown with instant switch.
- Save As New Profile, Overwrite Profile, Delete Profile.
- Import / Export JSON buttons.
- Clipboard auto-import watcher toggle.

### 4.7 Telemetry & Debug Tab
- Real-time mouse button activity indicators (LMB, RMB, MMB, M4, M5).
- Live debug console with auto-scroll, clear log, and export log.

---

## 5. Technical Implementation Details & Modularity

1. **Helper Component Module (`src/ui_components.py`):**
   - `ModernCard`: Clean CustomTkinter container frame with rounded corners (`corner_radius=10`), dark surface (`#141822`), border (`#232b3b`), title header with icon and optional badge.
   - `ModernSlider`: Standardized horizontal slider with label, direct text entry, and value change callbacks.
   - `ModernSwitch`: Toggle switch with title, subtitle description, and reactive state.
   - `StatusPill`: Compact colored telemetry badge for header and footer status bars.
2. **Master UI Refactoring (`src/ui.py`):**
   - Retain `ViewerApp` as the master controller for all window events, threads, and configs.
   - Refactor tab methods (`_show_aimbot_tab`, `_show_vision_tab`, `_show_general_tab`, `_show_config_tab`, `_show_debug_tab`) into 2-column card layouts.
3. **Localization (`locales/vi.json`):**
   - Complete Vietnamese localization file.
   - Register `"vi": "Tiếng Việt"` in `src/utils/i18n.py`.

---

## 6. Verification & Validation Criteria
1. **Visual Alignment:** All 2-column cards fit cleanly without horizontal scroll at default geometry (`1020x680`).
2. **Functionality Check:**
   - Sliders properly update config and trigger live tracking adjustments.
   - Start / Stop button immediately toggles the aim loop and updates HUD on PC 2.
   - Keybind capture works reliably when pressing mouse or keyboard buttons.
   - Profile saving and loading correctly preserves all WindMouse and vision settings.
3. **Performance:** No memory leaks or frame rate drop in `CaptureService` or `AimTracker`.
