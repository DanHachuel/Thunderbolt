"""Devolve o nome do processo com a janela em primeiro plano. Uso interno do launcher."""
import ctypes

user32 = ctypes.windll.user32
hwnd = user32.GetForegroundWindow()
if not hwnd:
    print("unknown")
else:
    pid = ctypes.c_ulong(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil
        print(psutil.Process(int(pid.value)).name())
    except Exception:
        print("unknown")
