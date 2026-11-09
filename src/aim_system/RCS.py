"""
RCS (Recoil Control System) 模組
處理後座力補償邏輯
"""
from src.utils.debug_logger import log_print
import time
import threading
from src.utils.config import config
from src.utils.activation import is_binding_pressed


# 全局變量用於管理 RCS 狀態
_rcs_state = {
    "is_active": False,  # RCS 是否啟動
    "last_click_time": 0.0,  # 上次點擊時間（用於檢測快速點擊）
    "button_press_time": None,  # 按鈕按下時間（用於檢測長按）
    "rcs_thread": None,  # RCS 線程
    "rcs_lock": threading.Lock()  # 線程鎖
}

# Y 軸解鎖狀態管理
_y_release_state = {
    "is_released": False,  # Y 軸是否已解鎖
    "release_start_time": None,  # 解鎖開始時間
    "release_duration": 0.0,  # 解鎖持續時間（秒）
    "release_lock": threading.Lock()  # 線程鎖
}


def _rcs_pull_loop(controller, pull_speed, move_queue=None):
    """
    RCS pull loop.

    Movement is pushed onto the shared move queue with the ``"rcs"`` tag when a
    queue is available, instead of calling ``controller.move()`` directly. Direct
    calls bypass the queue and therefore race the aimbot on the same Y axis (the
    flick and the recoil compensation could both write the same frame).

    Args:
        controller: Mouse controller (fallback when no queue is provided)
        pull_speed: Pull speed (1-20)
        move_queue: Optional shared queue accepting ``(dx, dy, delay, tag)``
    """
    # pull_speed is 1-20; convert to a per-loop movement amount.
    move_amount = pull_speed * 0.5

    while True:
        with _rcs_state["rcs_lock"]:
            if not _rcs_state["is_active"]:
                break

        try:
            if move_queue is not None:
                try:
                    move_queue.put_nowait((0, move_amount, 0.0, "rcs"))
                except Exception:
                    # Queue full: drop this tick instead of blocking the loop.
                    pass
            else:
                # Legacy fallback (no queue wired): direct controller call.
                controller.move(0, move_amount)
        except Exception as e:
            log_print(f"[RCS] Move error: {e}")
            break

        # ~80 FPS loop
        time.sleep(1.0 / 80.0)


def check_rcs_activation(activation_delay, rapid_click_threshold):
    """
    檢查 RCS 是否應該啟動
    
    Args:
        activation_delay: 啟動延遲（毫秒）
        rapid_click_threshold: 快速點擊閾值（毫秒）
        
    Returns:
        bool: 是否應該啟動 RCS
    """
    now = time.time()
    
    # 檢查左鍵是否按下
    left_button_pressed = bool(is_binding_pressed(getattr(config, "rcs_keybind", 0)))
    
    with _rcs_state["rcs_lock"]:
        if left_button_pressed:
            # 如果按鈕剛按下，記錄按下時間
            if _rcs_state["button_press_time"] is None:
                _rcs_state["button_press_time"] = now
                # 檢查快速點擊（按鈕剛按下時，檢查與上次點擊的間隔）
                if _rcs_state["last_click_time"] > 0:
                    click_interval = (now - _rcs_state["last_click_time"]) * 1000  # 轉換為毫秒
                    if click_interval <= rapid_click_threshold:
                        _rcs_state["last_click_time"] = now
                        return True
                _rcs_state["last_click_time"] = now
            
            # 檢查是否按住超過 activation_delay
            if _rcs_state["button_press_time"] is not None:
                hold_time = (now - _rcs_state["button_press_time"]) * 1000  # 轉換為毫秒
                if hold_time >= activation_delay:
                    return True
        else:
            # 按鈕未按下，重置按下時間
            if _rcs_state["button_press_time"] is not None:
                # 按鈕剛釋放，記錄為點擊時間（用於下次快速點擊檢測）
                _rcs_state["last_click_time"] = now
            _rcs_state["button_press_time"] = None
    
    return False


def start_rcs(controller, pull_speed, move_queue=None):
    """
    Start RCS.

    Args:
        controller: Mouse controller (fallback when no queue is available)
        pull_speed: Pull speed (1-20)
        move_queue: Optional shared queue; when given, RCS movement is tagged
            ``"rcs"`` and serialised with the aimbot instead of racing it.
    """
    with _rcs_state["rcs_lock"]:
        if _rcs_state["is_active"]:
            return  # already running

        _rcs_state["is_active"] = True

        # If the thread is still alive, reuse it.
        if _rcs_state["rcs_thread"] is not None and _rcs_state["rcs_thread"].is_alive():
            return

        _rcs_state["rcs_thread"] = threading.Thread(
            target=_rcs_pull_loop,
            args=(controller, pull_speed, move_queue),
            daemon=True
        )
        _rcs_state["rcs_thread"].start()


def stop_rcs():
    """
    停止 RCS
    """
    with _rcs_state["rcs_lock"]:
        _rcs_state["is_active"] = False
        _rcs_state["button_press_time"] = None


def is_rcs_active():
    """
    檢查 RCS 是否正在運行
    
    Returns:
        bool: RCS 是否啟動
    """
    with _rcs_state["rcs_lock"]:
        return _rcs_state["is_active"]


def process_rcs(controller, pull_speed, activation_delay, rapid_click_threshold, move_queue=None):
    """
    Handle RCS every frame.

    Args:
        controller: Mouse controller (fallback when no queue is provided)
        pull_speed: Pull speed (1-20)
        activation_delay: Activation delay (ms)
        rapid_click_threshold: Rapid click threshold (ms)
        move_queue: Optional shared queue; RCS commands are tagged ``"rcs"``

    Returns:
        bool: whether RCS is currently active (for aimbot integration)
    """
    if not getattr(config, "enablercs", False):
        stop_rcs()
        return False
    
    # Check whether RCS should engage
    should_activate = check_rcs_activation(activation_delay, rapid_click_threshold)
    
    if should_activate:
        start_rcs(controller, pull_speed, move_queue=move_queue)
    else:
        # 檢查左鍵是否還按下，如果沒有按下則停止 RCS
        if not is_binding_pressed(getattr(config, "rcs_keybind", 0)):
            stop_rcs()
    
    return is_rcs_active()


def check_y_release():
    """
    檢查 Y 軸是否應該解鎖（每幀調用）
    
    當左鍵按下時，啟動 Y 軸解鎖計時器，在指定時間內解鎖 Y 軸控制
    
    Returns:
        bool: Y 軸是否應該解鎖（True = 解鎖，aimbot 不控制 Y 軸）
    """
    # 檢查功能是否啟用
    if not getattr(config, "rcs_release_y_enabled", False):
        with _y_release_state["release_lock"]:
            _y_release_state["is_released"] = False
            _y_release_state["release_start_time"] = None
        return False
    
    release_duration = float(getattr(config, "rcs_release_y_duration", 1.0))
    # 限制範圍在 0.1~5 秒
    release_duration = max(0.1, min(5.0, release_duration))
    
    now = time.time()
    left_button_pressed = bool(is_binding_pressed(getattr(config, "rcs_keybind", 0)))
    
    with _y_release_state["release_lock"]:
        if left_button_pressed:
            # 如果按鈕剛按下，啟動解鎖計時器
            if _y_release_state["release_start_time"] is None:
                _y_release_state["release_start_time"] = now
                _y_release_state["release_duration"] = release_duration
                _y_release_state["is_released"] = True
            else:
                # 檢查是否還在解鎖時間內
                elapsed = now - _y_release_state["release_start_time"]
                if elapsed < release_duration:
                    _y_release_state["is_released"] = True
                else:
                    # 解鎖時間已過，但按鈕仍按下，不重置（等待按鈕釋放）
                    _y_release_state["is_released"] = False
        else:
            # 按鈕未按下，重置解鎖狀態
            _y_release_state["is_released"] = False
            _y_release_state["release_start_time"] = None
    
    return _y_release_state["is_released"]


def is_y_released():
    """
    檢查 Y 軸是否正在解鎖
    
    Returns:
        bool: Y 軸是否解鎖
    """
    with _y_release_state["release_lock"]:
        return _y_release_state["is_released"]

