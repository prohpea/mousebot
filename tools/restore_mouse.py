"""Release every held/locked mouse state on the MAKCU device.

Why this exists: the app keeps button-mask locks (lock_ml/lock_mr/...) and
button-down state inside the MAKCU firmware, not in the process. A forced kill
(taskkill / Stop-Process -Force) skips Mouse.cleanup(), so the firmware keeps
those locks and the physical mouse stops working until the state is cleared or
the device is replugged.

This sends only *release* commands: every lock off, every button up. It cannot
press or move anything.

Run:  venv\\Scripts\\python.exe tools\\restore_mouse.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BAUD_RATES = [4_000_000, 2_000_000, 115_200]

# Release commands understood by the MAKCU firmware. Order matters: drop button
# locks before releasing the buttons themselves.
RELEASE_CMDS = [
    "km.lock_ml(0)",
    "km.lock_mr(0)",
    "km.lock_mm(0)",
    "km.lock_ms1(0)",
    "km.lock_ms2(0)",
    # Movement-axis locks (SerialAPI.lock_movement_x/y send these).
    "km.lock_mx(0)",
    "km.lock_my(0)",
    "km.left(0)",
    "km.right(0)",
    "km.middle(0)",
    # Leave button reporting ENABLED (this is what connect() sends). Setting it
    # to 0 would stop the device tracking physical buttons.
    "km.buttons(1)",
]

OUT = Path(__file__).resolve().parent
LINES = []


def say(msg=""):
    print(msg)
    LINES.append(str(msg))


def find_candidate_ports():
    from serial.tools import list_ports

    supported = ("1A86:55D3", "1A86:5523", "1A86:7523", "1A86:5740", "10C4:EA60")
    found = []
    for port in list_ports.comports():
        hwid = (port.hwid or "").upper()
        if any(vid in hwid for vid in supported):
            found.append((port.device, port.description))
    return found


def probe_and_release(port_name, baud):
    import serial

    ser = None
    try:
        ser = serial.Serial(port_name, baud, timeout=0.3)
        time.sleep(0.15)
        ser.reset_input_buffer()
        ser.write(b"km.version()\r")
        ser.flush()

        resp = b""
        deadline = time.time() + 0.5
        while time.time() < deadline:
            if ser.in_waiting:
                resp += ser.read(ser.in_waiting)
                if b"MAKCU" in resp.upper():
                    break
            time.sleep(0.01)

        if b"MAKCU" not in resp.upper():
            say(f"  {port_name}@{baud}: no MAKCU response ({resp[:40]!r})")
            return False

        say(f"  {port_name}@{baud}: device answered -> releasing state")

        for cmd in RELEASE_CMDS:
            ser.write(f"{cmd}\r".encode("ascii", "ignore"))
            ser.flush()
            time.sleep(0.02)
            say(f"    -> {cmd}")

        ser.reset_input_buffer()
        return True
    except Exception as exc:
        say(f"  {port_name}@{baud}: {type(exc).__name__}: {exc}")
        return False
    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass


def main():
    say("=== MAKCU mouse-state restore ===")

    ports = find_candidate_ports()
    if not ports:
        say("No supported serial device found. Is the MAKCU still plugged in?")
        say("Fastest alternative: unplug and replug the MAKCU USB cable.")
        OUT.joinpath("restore_mouse_report.txt").write_text("\n".join(LINES), encoding="utf-8")
        return 1

    say(f"candidate ports: {ports}")

    done = False
    for port_name, desc in ports:
        say(f"\n--- {port_name}  ({desc}) ---")
        for baud in BAUD_RATES:
            if probe_and_release(port_name, baud):
                done = True
                break
        if done:
            break

    say("\n=== RESULT ===")
    if done:
        say("Release commands sent. The physical mouse should work again")
        say("immediately — no replug needed.")
        say("If it still does not, unplug and replug the MAKCU cable: that")
        say("resets firmware state unconditionally.")
    else:
        say("Could not reach the device.")
        say("Unplug and replug the MAKCU USB cable — that resets its state.")

    OUT.joinpath("restore_mouse_report.txt").write_text("\n".join(LINES), encoding="utf-8")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
