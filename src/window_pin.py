"""웹캠 미리보기 창을 화면 우측 상단에 고정하고 항상 위에 띄운다 (Windows).

- '항상 위(topmost)'는 포커스와 별개다. 미리보기는 다른 창 위에 보이기만 하고,
  키 입력 포커스는 유튜브가 그대로 가진다 (SWP_NOACTIVATE 로 포커스를 뺏지 않는다).
- 유튜브 전체화면 위에도 보인다 (브라우저 전체화면도 보통 창이라 topmost 창이 위에 온다).
- 종료(ESC)는 미리보기 창을 한 번 클릭해 포커스를 준 뒤 누른다.
"""
import ctypes
import sys
from ctypes import wintypes

HWND_TOPMOST = wintypes.HWND(-1)   # 64비트에서 정수 -1 을 그대로 넘기면 잘못된 핸들이 된다
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
SPI_GETWORKAREA = 0x0030


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


_U32 = None


def _user32():
    global _U32
    if sys.platform != "win32":
        return None
    if _U32 is None:
        # ctypes.windll.user32 는 프로세스 공용이라 여기서 argtypes 를 바꾸면 다른 모듈의 호출이 깨진다
        # (2026-11-18: youtube_control 의 GetWindowRect 가 오류 -> 유튜브 제어 스레드가 죽음).
        # 그래서 이 모듈 전용으로 따로 연다.
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.FindWindowW.restype = wintypes.HWND
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetWindowPos.restype = wintypes.BOOL
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
        _U32 = u
    return _U32


def find_window(title):
    user32 = _user32()
    return user32.FindWindowW(None, title) if user32 else 0


def pin_top_right(title, margin=8):
    """창을 작업 영역(작업 표시줄 제외) 우측 상단으로 옮기고 항상 위로. 성공하면 True."""
    user32 = _user32()
    hwnd = find_window(title)
    if not hwnd:
        return False
    work, win = _RECT(), _RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
    user32.GetWindowRect(hwnd, ctypes.byref(win))
    width = win.right - win.left
    x, y = work.right - width - margin, work.top + margin
    return bool(user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE))


def keep_on_top(title):
    """위치·크기·포커스는 그대로 두고 맨 위로만 다시 올린다 (다른 topmost 창에 밀렸을 때 대비)."""
    user32 = _user32()
    hwnd = find_window(title)
    if hwnd:
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
