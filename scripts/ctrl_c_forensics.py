"""Instantâneo forense da consola no momento de um Ctrl+C espúrio.

Executado pelo launcher (scripts/cli.mjs) quando um Ctrl+C é ignorado, para
identificar a ORIGEM da interrupção na próxima rajada:

- registos de input da consola — um KEY_EVENT Ctrl+C (uChar=0x03 ou VK_C com
  Ctrl pressionado) prova entrega por teclado/terminal; a ausência de registo
  aponta para um CTRL_C_EVENT gerado por software (GenerateConsoleCtrlEvent);
- janela em primeiro plano — o utilizador estava no terminal nesse momento?
- processos anexados à consola — todos os candidatos a emissor do evento.

O filho herda a consola do launcher, logo o PeekConsoleInputW vê exactamente
os mesmos registos que o processo principal veria. Escreve JSON puro no
stdout; qualquer falha nunca afecta o comportamento do launcher.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time

LEFT_CTRL_PRESSED = 0x0008
RIGHT_CTRL_PRESSED = 0x0010
VK_C = 0x43
STD_INPUT_HANDLE = -10


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", ctypes.c_int),
        ("wRepeatCount", ctypes.c_short),
        ("wVirtualKeyCode", ctypes.c_short),
        ("wVirtualScanCode", ctypes.c_short),
        ("uChar", ctypes.c_wchar),
        ("dwControlKeyState", ctypes.c_uint),
    ]


class _EVENT(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("_pad", ctypes.c_byte * 32)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", ctypes.c_short), ("Event", _EVENT)]


def _input_records(kernel32) -> list[dict]:
    """Últimos registos pendentes do buffer de input da consola (sem consumir)."""
    conin = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    if not conin or conin == ctypes.c_void_p(-1).value:
        return []
    pending = ctypes.c_ulong(0)
    if not kernel32.GetNumberOfConsoleInputEvents(conin, ctypes.byref(pending)) or not pending.value:
        return []
    count = min(int(pending.value), 64)
    buffer = (INPUT_RECORD * count)()
    read = ctypes.c_ulong(0)
    if not kernel32.PeekConsoleInputW(conin, buffer, count, ctypes.byref(read)):
        return []
    records: list[dict] = []
    for index in range(int(read.value)):
        record = buffer[index]
        entry: dict = {"type": int(record.EventType)}
        if int(record.EventType) == 1:  # KEY_EVENT
            key = record.Event.KeyEvent
            ctrl_pressed = bool(key.dwControlKeyState & (LEFT_CTRL_PRESSED | RIGHT_CTRL_PRESSED))
            is_ctrl_c = key.uChar == "\x03" or (int(key.wVirtualKeyCode) == VK_C and ctrl_pressed)
            entry.update({
                "down": bool(key.bKeyDown),
                "vk": int(key.wVirtualKeyCode),
                "char": key.uChar.encode("unicode_escape").decode("ascii"),
                "ctrl": ctrl_pressed,
                "ctrl_c": bool(key.bKeyDown) and is_ctrl_c,
            })
        records.append(entry)
    return records


def _foreground() -> dict:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {}
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    pid = ctypes.c_ulong(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    snapshot = {"pid": int(pid.value), "title": buffer.value[:120]}
    try:
        import psutil

        snapshot["name"] = psutil.Process(int(pid.value)).name()
    except Exception:
        pass
    return snapshot


def _console_processes() -> dict:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = (ctypes.c_ulong * 64)()
    count = kernel32.GetConsoleProcessList(64, buffer)
    pids = [int(buffer[index]) for index in range(int(count))]
    snapshot = {"pids": pids}
    try:
        import psutil

        snapshot["names"] = {str(pid): psutil.Process(pid).name() for pid in pids}
    except Exception:
        pass
    return snapshot


def main() -> int:
    snapshot: dict = {"at": time.time()}
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        snapshot["input_records"] = _input_records(kernel32)
    except Exception as exc:  # forensics nunca pode quebrar o launcher
        snapshot["input_records_error"] = str(exc)[:200]
    try:
        snapshot["foreground"] = _foreground()
    except Exception as exc:
        snapshot["foreground_error"] = str(exc)[:200]
    try:
        snapshot["console"] = _console_processes()
    except Exception as exc:
        snapshot["console_error"] = str(exc)[:200]
    print(json.dumps(snapshot, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
