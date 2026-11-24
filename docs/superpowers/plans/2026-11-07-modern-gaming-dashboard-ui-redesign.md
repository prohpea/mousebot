# Modern Gaming Dashboard UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the CVM-colorBot v1.2.1 interface into a modern 2-column gaming dashboard with clean cards, real-time title bar status pills, a streamlined sidebar with an accessible Start/Stop engine button, and native Vietnamese localization.

**Architecture:** A reusable component library (`src/ui_components.py`) provides `ModernCard`, `ModernSlider`, `ModernSwitch`, and `StatusPill`. The master controller `ViewerApp` in `src/ui.py` is refactored to host a custom title bar with telemetry pills, an uncluttered 210px sidebar, and 2-column grid tabs for Combat, Vision, Hardware, Profiles, and Telemetry. 100% of underlying algorithm logic, thread loops, and config bindings are strictly preserved.

**Tech Stack:** Python 3.11, CustomTkinter 5.2.2, Tkinter, PIL, OpenCV, UDP Socket.

**Spec:** [docs/superpowers/specs/2026-11-07-modern-gaming-dashboard-ui-redesign.md](file:///c:/Users/TeamOS/Downloads/CVM-colorBot-v1.2.1-FullPackage/CVM-colorBot/docs/superpowers/specs/2026-11-07-modern-gaming-dashboard-ui-redesign.md)

## Global Constraints

- Must run cleanly in existing virtual environment with `customtkinter==5.2.2`.
- Default window geometry: `1020x680` (minimum `960x620`).
- Color palette: Surface `#141822`, Background `#0C0E14`, Border `#232B3B`, Accent Emerald `#10B981`, Accent Cyan `#06B6D4`, Crimson Danger `#F43F5E`.
- Card corner radius: `10px`, card border width: `1px`.
- Config persistence: Must preserve all existing keys in `config.json` and `config.burst_spray.json`.
- Preserve core aim loops without adding UI thread lockup.

## Review Focus

1. **Window Resize & Grid Overflow:** A user resizing the window or running at 100% / 125% DPI scale must not have cards clipped or horizontally scrollable.
2. **Pro vs. Simple Mode Toggle Reflow:** Toggling between Pro and Simple modes must dynamically adjust card visibility without leaving empty spaces in the 2-column grid.
3. **Keybind Capture Modal Stability:** Clicking the Key Bind button must not get stuck if the user clicks elsewhere or presses a modifier key.
4. **Live Telemetry Pill Formatting:** Title bar pills must cleanly format high FPS and sub-millisecond delays (`120.4 FPS`, `0.6 ms`) without jittering or overflowing.
5. **Language Switch Dynamic Refresh:** Switching between Tiếng Việt and English must update all card titles, slider labels, and tooltips without requiring app restart.

---

### Task 1: Vietnamese Localization & i18n Integration

**Files:**
- Create: `locales/vi.json`
- Modify: `src/utils/i18n.py:5-15`
- Test: `tests/test_i18n_vi.py`

**Interfaces:**
- Consumes: `src/utils/i18n.py` (`t(key)`, `set_language(lang)`)
- Produces: Complete Vietnamese translation dictionary covering all cards, buttons, telemetry labels, and tooltips.

- [ ] **Step 1: Write the failing test for Vietnamese localization**

Create `tests/test_i18n_vi.py`:
```python
import os
import pytest
from src.utils.i18n import i18n, t

def test_vietnamese_locale_exists():
    available = dict(i18n.available())
    assert "vi" in available
    assert available["vi"] == "Tiếng Việt"

def test_vietnamese_translations():
    i18n.set_language("vi")
    assert t("START") == "BẮT ĐẦU" or t("START") == "CHẠY"
    assert t("Target Color Preset") == "Màu Mục Tiêu" or "Mục Tiêu" in t("Target Color Preset")
    assert t("Main Aimbot") == "Aimbot Chính"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_i18n_vi.py -v`  
Expected: FAIL ("vi not in available").

- [ ] **Step 3: Implement `locales/vi.json` and update `src/utils/i18n.py`**

1. Register `"vi": "Tiếng Việt"` in `LANGUAGE_NAMES` in `src/utils/i18n.py`.
2. Create `locales/vi.json` with comprehensive translations for:
   - `START` ("BẮT ĐẦU"), `STOP` ("DỪNG LẠI"), `STARTING...` ("ĐANG KHỞI ĐỘNG..."), `STOPPING...` ("ĐANG DỪNG...")
   - Card headers: `Target & FOV` ("Mục Tiêu & FOV"), `WindMouse Humanizer` ("Đường Chuột WindMouse"), `Speeds & Recoil` ("Tốc Độ & Khử Giật"), `Anti-Tremor & Timing` ("Lọc Rung & Phản Xạ"), `Color & Vision` ("Màu Sắc & Nhận Diện"), `Hardware & Stream` ("Phần Cứng & Truyền Hình Ảnh"), `Profiles` ("Cấu Hình Profiles"), `Telemetry & Debug` ("Nhật Ký & Thử Nghiệm").
   - Controls: `FOV Size` ("Bán Kính FOV"), `Aim Key` ("Phím Kích Hoạt"), `Aim Mode` ("Chế Độ Aim"), `Gravity` ("Lực Hút Trọng Lực"), `Wind` ("Độ Nhiễu Tự Nhiên"), `X-Speed` ("Tốc Độ Ngang"), `Y-Speed` ("Tốc Độ Dọc"), `Recoil Immunity` ("Chống Giật Bay Đầu Khi Sấy"), `Audio Feedback` ("Tiếng Bíp Phản Hồi Tai Nghe").

- [ ] **Step 4: Run test to verify it passes**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_i18n_vi.py -v`  
Expected: PASS.

- [ ] **Step 5: Verify language fallback and reset**

Ensure calling `i18n.set_language("en")` restores English strings cleanly without residual cache errors.

---

### Task 2: Modern UI Component Suite (`src/ui_components.py`)

**Files:**
- Create: `src/ui_components.py`
- Test: `tests/test_ui_components.py`

**Interfaces:**
- Consumes: `customtkinter`
- Produces:
  - `ModernCard(parent, title, icon=None, badge_text=None, **kwargs) -> ctk.CTkFrame`
  - `ModernSlider(parent, label, key, min_val, max_val, init_val, command, is_float=False) -> ctk.CTkFrame`
  - `ModernSwitch(parent, title, variable, command, subtitle=None) -> ctk.CTkFrame`
  - `StatusPill(parent, label, value, dot_color="#10B981") -> ctk.CTkFrame`

- [ ] **Step 1: Write unit tests for modern components**

Create `tests/test_ui_components.py`:
```python
import customtkinter as ctk
import tkinter as tk
import pytest
from src.ui_components import ModernCard, ModernSlider, ModernSwitch, StatusPill

def test_modern_card_creation():
    root = ctk.CTk()
    card = ModernCard(root, title="Targeting & FOV", icon="🎯", badge_text="Core")
    assert card is not None
    assert card.title == "Targeting & FOV"
    root.destroy()

def test_modern_slider_value_change():
    root = ctk.CTk()
    changed_val = []
    slider = ModernSlider(root, label="FOV Size", key="fovsize", min_val=10, max_val=150, init_val=28,
                          command=lambda v: changed_val.append(v), is_float=False)
    slider.set_value(40)
    assert slider.get_value() == 40
    root.destroy()

def test_status_pill():
    root = ctk.CTk()
    pill = StatusPill(root, label="OBS UDP", value="120 FPS", dot_color="#10B981")
    pill.update_value("144 FPS", dot_color="#06B6D4")
    assert pill.value_text == "144 FPS"
    root.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_ui_components.py -v`  
Expected: FAIL ("ModuleNotFoundError: No module named 'src.ui_components'").

- [ ] **Step 3: Implement `src/ui_components.py`**

Implement:
- `ModernCard`: A `ctk.CTkFrame` styled with `fg_color="#141822"`, `border_color="#232B3B"`, `border_width=1`, `corner_radius=10`. Header bar with icon, bold title (`font=("Segoe UI", 12, "bold")`, text `#10B981` or `#06B6D4`), optional badge (`#1A2130`, text `#94A3B8`), content container frame.
- `ModernSlider`: A horizontal row with title (`text-slate-300`), value label badge (`font=("Consolas", 11, "bold")`), sleek `ctk.CTkSlider` (`progress_color="#10B981"`, `button_color="#10B981"`, `button_hover_color="#34D399"`), and direct numeric entry box. Clamps values properly.
- `ModernSwitch`: Container row with title, description subtitle (`text-slate-400`, 9pt), and reactive `ctk.CTkSwitch` (`progress_color="#10B981"`).
- `StatusPill`: Capsule frame (`corner_radius=12`, `fg_color="#171C28"`, `border_color="#252F44"`, `border_width=1`) with a colored circular dot canvas/label and formatted text.

- [ ] **Step 4: Run test to verify it passes**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_ui_components.py -v`  
Expected: PASS.

---

### Task 3: Modern Header & Title Bar with Real-Time Status Pills

**Files:**
- Modify: `src/ui.py:486-601` (`_build_title_bar`, `_update_performance_stats`, `_update_connection_status_loop`)
- Test: `tests/test_title_bar.py`

**Interfaces:**
- Consumes: `src/ui_components.py` (`StatusPill`)
- Produces: Updated title bar layout with telemetry pills and window controls.

- [ ] **Step 1: Write test for Title Bar components and status pills**

Create `tests/test_title_bar.py`:
```python
import pytest
from unittest.mock import MagicMock
import customtkinter as ctk

def test_title_bar_pills():
    from src.ui import ViewerApp
    tracker_mock = MagicMock()
    capture_mock = MagicMock()
    app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
    
    assert hasattr(app, "pill_fps")
    assert hasattr(app, "pill_delay")
    assert hasattr(app, "pill_hardware")
    
    # Test telemetry update
    app.pill_fps.update_value("120 FPS")
    assert "120" in app.pill_fps.value_text
    
    app.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_title_bar.py -v`  
Expected: FAIL (AttributeError: 'ViewerApp' object has no attribute 'pill_fps').

- [ ] **Step 3: Implement Title Bar in `src/ui.py`**

1. In `_build_title_bar`:
   - Left: Logo icon + App name ("CVM COLORBOT") + Version pill ("v1.2.1").
   - Center/Right:
     - `self.pill_fps = StatusPill(title_container, "OBS UDP", "FPS: --", dot_color="#10B981")`
     - `self.pill_delay = StatusPill(title_container, "Delay", "-- ms", dot_color="#06B6D4")`
     - `self.pill_hardware = StatusPill(title_container, "Hardware", "Serial", dot_color="#94A3B8")`
   - Far Right: Mode toggle ("Pro" / "Simple"), Minimize ("─"), Maximize ("▢"), Close ("✕").
2. In `_update_performance_stats`:
   - Update `self.pill_fps.update_value(f"{fps:.0f} FPS")`.
   - Update `self.pill_delay.update_value(f"{delay_ms:.1f} ms")`.
3. In `_update_connection_status_loop`:
   - Update `self.pill_hardware.update_value(hw_label, dot_color="#10B981" if is_connected else "#F43F5E")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_title_bar.py -v`  
Expected: PASS.

---

### Task 4: Streamlined Modern Sidebar with Large Engine Button

**Files:**
- Modify: `src/ui.py:601-848` (`_build_sidebar`, `_refresh_runtime_button`)
- Test: `tests/test_sidebar.py`

**Interfaces:**
- Consumes: `src/ui.py` methods
- Produces: Uncluttered 210px sidebar layout with large action button, modern nav pills, and active profile badge.

- [ ] **Step 1: Write unit test for Sidebar navigation and Engine button**

Create `tests/test_sidebar.py`:
```python
import pytest
from unittest.mock import MagicMock
from src.ui import ViewerApp

def test_sidebar_structure():
    tracker_mock = MagicMock()
    capture_mock = MagicMock()
    app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
    
    assert app.sidebar.winfo_reqwidth() >= 195
    assert hasattr(app, "runtime_btn")
    assert hasattr(app, "nav_buttons")
    assert "Combat" in app.nav_buttons
    assert "Vision" in app.nav_buttons
    assert "Hardware" in app.nav_buttons
    assert "Profiles" in app.nav_buttons
    assert "Telemetry" in app.nav_buttons
    
    app.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_sidebar.py -v`  
Expected: FAIL (key mismatch in `nav_buttons`).

- [ ] **Step 3: Implement Modern Sidebar in `src/ui.py`**

1. Set sidebar width to `210`.
2. Place large `runtime_btn` at top of sidebar:
   - Height `38px`, font `("Segoe UI", 12, "bold")`.
   - Running: background `#10B981` (Emerald), hover `#34D399`, text `#04140A`, label "RUNNING (ACTIVE)".
   - Stopped: background `#F43F5E` (Crimson), hover `#FB7185`, text `#FFFFFF`, label "START ENGINE".
3. Navigation menu:
   - `🎯 Combat` -> `_show_aimbot_tab`
   - `👁️ Vision` -> `_show_vision_tab`
   - `⚡ Hardware & Stream` -> `_show_general_tab`
   - `📁 Profiles` -> `_show_config_tab`
   - `📊 Telemetry & Debug` -> `_show_debug_tab`
   - Add modern indicator pill on active nav item.
4. Active Profile Card at bottom:
   - Displays loaded profile name (e.g. `config.burst_spray.json`).
   - Quick language toggle button (Tiếng Việt / English).

- [ ] **Step 4: Run test to verify it passes**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_sidebar.py -v`  
Expected: PASS.

---

### Task 5: Combat Tab 2-Column Card Grid (Main & Sec Aimbot)

**Files:**
- Modify: `src/ui.py:4690-5230` (`_show_aimbot_tab`, `_show_sec_aimbot_tab`)
- Test: `tests/test_combat_tab.py`

**Interfaces:**
- Consumes: `src/ui_components.py` (`ModernCard`, `ModernSlider`, `ModernSwitch`)
- Produces: 2-column card grid for Combat tab with Target/FOV, WindMouse, Speeds/Recoil, and Anti-Tremor/Beep cards.

- [ ] **Step 1: Write test for Combat tab 2-column cards**

Create `tests/test_combat_tab.py`:
```python
import pytest
from unittest.mock import MagicMock
from src.ui import ViewerApp
from src.utils.config import config

def test_combat_tab_cards():
    tracker_mock = MagicMock()
    capture_mock = MagicMock()
    app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
    app._show_aimbot_tab()
    
    # Verify sub-pills
    assert app._active_tab_name == "Main Aimbot"
    
    # Verify cards exist
    assert hasattr(app, "card_targeting")
    assert hasattr(app, "card_windmouse")
    assert hasattr(app, "card_speeds")
    assert hasattr(app, "card_humanization")
    
    # Test slider update sync
    app._on_fovsize_changed(35)
    assert config.fovsize == 35
    
    app.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_combat_tab.py -v`  
Expected: FAIL (missing card attributes).

- [ ] **Step 3: Implement 2-Column Grid in `_show_aimbot_tab` and `_show_sec_aimbot_tab`**

1. Top bar: Sub-nav switcher (`Aimbot Chính` | `Aimbot Phụ`) and Master Enable switch.
2. Grid container: `grid_columnconfigure(0, weight=1)`, `grid_columnconfigure(1, weight=1)`.
3. **Column 0, Row 0 - `self.card_targeting` (Target & FOV):**
   - Aim Mode dropdown (`Normal / WindMouse`, `Flick`, `Silent`, `Bezier`, `PID`).
   - Aim Key binding button with key recorder listener.
   - Activation type (`Giữ phím / Hold`, `Bật/Tắt / Toggle`).
   - FOV Slider with direct entry.
   - Target Bone dropdown (`Đầu / Head`, `Ngực / Neck/Chest`, `Gần nhất / Closest`).
   - Expandable ADS Row (ADS Key, ADS FOV toggle).
4. **Column 1, Row 0 - `self.card_windmouse` (Algorithm Tuning):**
   - When Normal Mode: Gravity slider (`wm_gravity`), Wind slider (`wm_wind`), Max Step (`wm_max_step`), Min Step (`wm_min_step`), Min/Max Delays.
   - When other modes: Dynamically displays Flick / Silent / PID sliders.
5. **Column 0, Row 1 - `self.card_speeds` (Tốc Độ & Bù Giật Sấy):**
   - X Speed slider (`normal_x_speed`).
   - Y Speed slider (`normal_y_speed`).
   - Y-Decouple Recoil Immunity toggle.
   - Sensitivity & Mouse DPI calibration.
6. **Column 1, Row 1 - `self.card_humanization` (Lọc Rung Tay & Phản Xạ):**
   - Anti-tremor deadband slider.
   - Reaction time range (`smooth_reaction_min`, `smooth_reaction_max`).
   - Directional flip filter toggle.
   - Audio Feedback Beep toggle (UDP 4455).
7. Apply identical clean card structure to `_show_sec_aimbot_tab` for Secondary Aimbot.

- [ ] **Step 4: Run test to verify it passes**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_combat_tab.py -v`  
Expected: PASS.

---

### Task 6: Vision, Hardware, Profiles & Telemetry Tabs Card Refactoring

**Files:**
- Modify: `src/ui.py:1442-1520` (`_show_vision_tab`)
- Modify: `src/ui.py:1524-2000` (`_show_general_tab`)
- Modify: `src/ui.py:5593-5797` (`_show_config_tab`, `_show_debug_tab`)
- Test: `tests/test_remaining_tabs.py`

**Interfaces:**
- Consumes: `src/ui_components.py`
- Produces: 2-column card layouts across Vision, Hardware & Stream, Profiles, and Telemetry tabs.

- [ ] **Step 1: Write test for remaining tabs**

Create `tests/test_remaining_tabs.py`:
```python
import pytest
from unittest.mock import MagicMock
from src.ui import ViewerApp

def test_remaining_tabs_switch():
    tracker_mock = MagicMock()
    capture_mock = MagicMock()
    app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
    
    app._show_vision_tab()
    assert hasattr(app, "card_color_preset")
    assert hasattr(app, "card_hsv_tuning")
    
    app._show_general_tab()
    assert hasattr(app, "card_mouse_api")
    assert hasattr(app, "card_capture_service")
    
    app._show_config_tab()
    assert hasattr(app, "card_profile_manager")
    
    app._show_debug_tab()
    assert hasattr(app, "card_mouse_monitor")
    assert hasattr(app, "card_system_logs")
    
    app.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_remaining_tabs.py -v`  
Expected: FAIL (missing card attributes).

- [ ] **Step 3: Refactor Vision Tab (`_show_vision_tab`)**
  - Card 1: Target Color Preset (`yellow`, `purple`, `red`, `custom`).
  - Card 2: Custom HSV Calibration (Launch HSV Preview button, Min/Max sliders).
  - Card 3: Contour & Morphology Filters (Merge Distance, Min Contour Points, Bounding Box constraints).

- [ ] **Step 4: Refactor Hardware & Stream Tab (`_show_general_tab`)**
  - Card 1: Hardware Mouse API (Backend dropdown, COM port, Baud rate, 4M Auto-Switch, Test Move button).
  - Card 2: Video Stream Capture (Backend dropdown: OBS UDP / NDI / DDA / Card, Host/Port inputs, TurboJPEG indicator).
  - Card 3: Calibration & Coordinate Center (Invert X/Y, Range adjustments).

- [ ] **Step 5: Refactor Profiles Tab (`_show_config_tab`)**
  - Card 1: Active Profile Manager (Selector dropdown, Save As, Overwrite, Delete).
  - Card 2: Import / Export JSON (Export to file, Import file, Clipboard Auto-Import toggle).

- [ ] **Step 6: Refactor Telemetry & Debug Tab (`_show_debug_tab`)**
  - Card 1: Live Mouse Input Activity (LMB, RMB, MMB, M4, M5 click counters and visual pulse).
  - Card 2: System Log Console (Real-time log viewer, auto-scroll, clear log, export log).

- [ ] **Step 7: Run test to verify it passes**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_remaining_tabs.py -v`  
Expected: PASS.

---

### Task 7: End-to-End Integration, Geometry & Pro/Simple Mode Verification

**Files:**
- Modify: `src/ui.py`
- Test: `tests/test_e2e_ui.py`

**Interfaces:**
- Full system integration test

- [ ] **Step 1: Write E2E integration test**

Create `tests/test_e2e_ui.py`:
```python
import pytest
from unittest.mock import MagicMock
from src.ui import ViewerApp
from src.utils.config import config
from src.utils.i18n import i18n

def test_e2e_ui_workflow():
    tracker_mock = MagicMock()
    capture_mock = MagicMock()
    app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
    
    # 1. Test language switch
    app._on_language_changed("Tiếng Việt")
    assert i18n.language == "vi"
    
    # 2. Test Pro/Simple mode toggle
    initial_mode = app._ui_pro_mode
    app._toggle_pro_mode()
    assert app._ui_pro_mode != initial_mode
    
    # 3. Test geometry constraints
    assert app.winfo_width() >= 960 or app.winfo_reqwidth() >= 960
    
    # 4. Test engine start/stop cycle
    app._toggle_runtime()
    app._toggle_runtime()
    
    app.destroy()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `c:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot\venv\Scripts\pytest.exe tests/test_e2e_ui.py -v`  
Expected: PASS.

- [ ] **Step 3: Verification of live app launch**

Run standalone launch test script:
```powershell
.\venv\Scripts\python.exe -c "from src.ui import ViewerApp; print('UI imported successfully')"
```
Ensure zero syntax errors, zero missing imports, and clean packaging.
