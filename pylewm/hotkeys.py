import pylewm.commands
import sys, ctypes
from ctypes import windll, CFUNCTYPE, POINTER, c_int, c_uint, c_void_p, byref, c_ulong, pointer, addressof, create_string_buffer
import win32con, win32api, win32gui, atexit
import ctypes.wintypes as wintypes

import traceback, threading
import copy

queue_command = None

class Mode:
    def __init__(self, hotkeys={}, captureAll=True):
        self.hotkeys = []
        self.captureAll = captureAll
        for key, bind in hotkeys.items():
            if hasattr(bind, "pylewm_callback"):
                bind = bind.pylewm_callback
            self.hotkeys.append((KeySpec.fromTuple(key), bind))

    def handle_key(self, key, isMod):
        if key.key == "esc":
            # Escape always escapes out of modes
            queue_command(escape_mode)
            return True
        for bnd in self.hotkeys:
            if bnd[0] == key:
                queue_command(bnd[1])
                return True
        if not isMod and self.captureAll:
            return True
        else:
            return None

    def end_mode(self):
        pass

    def __call__(self):
        with ModeLock:
            ModeStack.insert(0, self)

class KeyPrompt(Mode):
    def __init__(self, callback, escape_cancels=True):
        self.callback = callback
        self.escape_cancels = escape_cancels

    def handle_key(self, key, isMod):
        if not isMod:
            if key.down:
                prompt = self
                storeKey = copy.deepcopy(key)
                def handle():
                    if not self.escape_cancels or key.key != "esc":
                        prompt.callback(storeKey)
                    escape_mode()
                queue_command(handle)
            return True
        else:
            return False

def prompt_key(callback):
    KeyPrompt(callback)()

@pylewm.commands.PyleCommand
def escape_mode():
    """ Escape whatever hotkey mode we're currently in. """
    with ModeLock:
        if ModeStack:
            ModeStack[0].end_mode()
            ModeStack.pop(0)

@pylewm.commands.PyleCommand
def absorb_key():
    """ Absorb whatever key is being pressed. """
    pass

class ModPair:
    def __init__(self, left=False, right=False, either=False, any_state=False):
        self.left = left
        self.right = right
        self.either = either
        self.any_state = any_state
        
    def __eq__(self, other):
        if self.any_state or other.any_state:
            return True
        if self.either:
            return other.left or other.right or other.either
        if other.either:
            return self.left or self.right
        return self.left == other.left and self.right == other.right
        
    def __repr__(self):
        str = ""
        if self.either:
            str += "A"
        if self.left:
            str += "L"
        if self.right:
            str += "R"
        if self.any_state:
            str += "?"
        if not str:
            str = "-"
        return str
      
    @property
    def isSet(self):
        return self.left or self.right or self.either
        
    def update(self, matchKey, matchSet, leftKey, rightKey):
        isMod = 0
        if matchKey == leftKey and leftKey != 0:
            self.left = matchSet
            isMod = 1
        if matchKey == rightKey and rightKey != 0:
            self.right = matchSet
            isMod = 2
        self.either = False
        return isMod

class KeySpec:
    def __init__(self, key):
        self.alt = ModPair()
        self.win = ModPair()
        self.ctrl = ModPair()
        self.shift = ModPair()
        self.app = ModPair()
        self.key = key
        self.down = True
      
    @staticmethod
    def fromTuple(key):
        spec = KeySpec('')
        if isinstance(key, str):
            spec.key = key.lower()
        else:
            for elem in key:
                if elem.lower() == "ralt":
                    spec.alt.right = True
                elif elem.lower() == "lalt":
                    spec.alt.left = True
                elif elem.lower() == "alt":
                    spec.alt.either = True
                elif elem.lower() == "rctrl":
                    spec.ctrl.right = True
                elif elem.lower() == "lctrl":
                    spec.ctrl.left = True
                elif elem.lower() == "ctrl":
                    spec.ctrl.either = True
                elif elem.lower() == "rshift":
                    spec.shift.right = True
                elif elem.lower() == "lshift":
                    spec.shift.left = True
                elif elem.lower() == "shift":
                    spec.shift.either = True
                elif elem.lower() == "rwin":
                    spec.win.right = True
                elif elem.lower() == "lwin":
                    spec.win.left = True
                elif elem.lower() == "win":
                    spec.win.either = True
                elif elem.lower() == "app":
                    spec.app.either = True
                elif elem.startswith('=') and elem != '=':
                    spec.key = elem[1:].lower()
                elif elem == 'any_mod':
                    spec.win.any_state = True
                    spec.ctrl.any_state = True
                    spec.alt.any_state = True
                    spec.shift.any_state = True
                    spec.app.any_state = True
                else:
                    spec.key = elem.lower()
        return spec

    def equals_combo(self, other):
        return self.alt == other.alt and self.win == other.win \
            and self.ctrl == other.ctrl and self.shift == other.shift \
            and self.key == other.key and self.app == other.app
    
    def __eq__(self, other):
        return self.equals_combo(other) and self.down == other.down
            
    def __str__(self):
        return str(self.__dict__)

    def __repr__(self):
        return repr(self.__dict__)
            
KeyBindings = []
ModeStack = []
ModeLock = threading.RLock()
ActiveKey = KeySpec('')

def register(key, callback):
    registerSpec(KeySpec.fromTuple(key), callback)
    
def registerSpec(keySpec, command):
    global KeyBindings
    if hasattr(command, "pylewm_callback"):
        command = command.pylewm_callback
    KeyBindings.append((keySpec, command))

def handle_python(isKeyDown, keyCode, scanCode):
    absorbKey = False
        
    # Handle modifiers
    isMod = 0
    isMod |= ActiveKey.alt.update(keyCode, isKeyDown, win32con.VK_LMENU, win32con.VK_RMENU)
    isMod |= ActiveKey.shift.update(keyCode, isKeyDown, win32con.VK_LSHIFT, win32con.VK_RSHIFT)
    isMod |= ActiveKey.ctrl.update(keyCode, isKeyDown, win32con.VK_LCONTROL, win32con.VK_RCONTROL)
    isMod |= ActiveKey.win.update(keyCode, isKeyDown, win32con.VK_LWIN, win32con.VK_RWIN)
    isMod |= ActiveKey.app.update(keyCode, isKeyDown, win32con.VK_APPS, 0)

    # Update active key
    ActiveKey.key = VKToChr(keyCode, scanCode)
    ActiveKey.down = isKeyDown

    # Check modes
    if ModeStack:
        with ModeLock:
            if ModeStack:
                handle_type = ModeStack[0].handle_key(ActiveKey, isMod)
                if handle_type is not None:
                    return handle_type

    # Check keybinds
    for bnd in KeyBindings:
        if bnd[0].key == ActiveKey.key:
            if bnd[0].equals_combo(ActiveKey):
                if ActiveKey.down:
                    queue_command(bnd[1])
                absorbKey = True

    return absorbKey

# TODO: Complete this map
VK_MAP = {
    win32con.VK_ESCAPE: "esc",
    win32con.VK_F1: "f1",
    win32con.VK_F2: "f2",
    win32con.VK_F3: "f3",
    win32con.VK_F4: "f4",
    win32con.VK_F5: "f5",
    win32con.VK_F6: "f6",
    win32con.VK_F7: "f7",
    win32con.VK_F8: "f8",
    win32con.VK_F9: "f9",
    win32con.VK_F10: "f10",
    win32con.VK_F11: "f11",
    win32con.VK_F12: "f12",
    win32con.VK_LCONTROL: "lctrl",
    win32con.VK_RCONTROL: "rctrl",
    win32con.VK_LMENU: "lalt",
    win32con.VK_RMENU: "ralt",
    win32con.VK_LSHIFT: "lshift",
    win32con.VK_RSHIFT: "rshift",
    win32con.VK_APPS: "app",
    win32con.VK_RETURN: "enter",
    win32con.VK_BACK: "backspace",
    win32con.VK_LEFT: "left",
    win32con.VK_RIGHT: "right",
    win32con.VK_UP: "up",
    win32con.VK_DOWN: "down",
}

KBState = (ctypes.c_byte * 256)()
def VKToChr(vk, sc):
    if vk in VK_MAP:
        return VK_MAP[vk]
    try:
        output = (ctypes.c_short * 3)()
        retCode = windll.user32.ToAscii(c_uint(vk), c_uint(sc), KBState, output, c_uint(0))
        return chr(output[0]).lower()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        sys.exit()
    
def wait_for_hotkeys():
    def handle_windows(nCode, wParam, lParam):
            isKeyDown = False
            isKeyUp = False
            if wParam == win32con.WM_KEYDOWN or wParam == win32con.WM_SYSKEYDOWN:
                isKeyDown = True
            if wParam == win32con.WM_KEYUP or wParam == win32con.WM_SYSKEYUP:
                isKeyUp = True
            
            shouldContinue = True
            if isKeyDown or isKeyUp:
                shouldContinue = not handle_python(isKeyDown, lParam[0], lParam[1])
            if shouldContinue:
                return windll.user32.CallNextHookEx(windowsHook, nCode, wParam, lParam)
            return 1

    HANDLER = CFUNCTYPE(c_uint, c_uint, c_uint, POINTER(c_uint))
    handlerPtr = HANDLER(handle_windows)

    windowsHook = windll.user32.SetWindowsHookExA(win32con.WH_KEYBOARD_LL, handlerPtr, win32api.GetModuleHandle(None), 0)
    atexit.register(windll.user32.UnhookWindowsHookEx, windowsHook)

    """
    def is_window_handle_cloaked(hwnd):
        output = (ctypes.c_uint * 1)()
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd,
            ctypes.c_uint(14),
            output, 4)
        return output[0] != 0
    HAS_HIDDEN = set()
    def handle_shell(hook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        if idObject == win32con.OBJID_WINDOW:
            if win32gui.IsWindow(hwnd) and not is_window_handle_cloaked(hwnd) and win32gui.IsWindowVisible(hwnd):
                print(f"LOCATIONCHANGE {hwnd:x} {win32gui.GetWindowText(hwnd)} - {win32gui.GetWindowRect(hwnd)}")

                rect = win32gui.GetWindowRect(hwnd)
                if (rect[0] != -10000 or rect[1] != -10000) and hwnd not in HAS_HIDDEN:
                    print("MOVE")
                    win32gui.SetWindowPos(hwnd,
                        win32con.HWND_BOTTOM,
                        -10000, -10000,
                        rect[2]-rect[0], rect[3]-rect[1],
                        win32con.SWP_NOACTIVATE | win32con.SWP_NOSIZE)
                    result = win32gui.GetWindowRect(hwnd)
                    print(f"result {result}")
                    HAS_HIDDEN.add(hwnd)

            if win32gui.IsWindow(hwnd) and not is_window_handle_cloaked(hwnd) and win32gui.IsWindowVisible(hwnd) and not hwnd in HAS_HIDDEN:
                print(f"PREHIDE {hwnd:x}")
                HAS_HIDDEN.add(hwnd)
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                #pylewm.commands.delay_pyle_command(0.5, lambda: win32gui.ShowWindow(hwnd, win32con.SW_SHOW))
                #rect = win32gui.GetWindowRect(hwnd)
                #win32gui.SetWindowPos(hwnd,
                    #win32con.HWND_BOTTOM,
                    #rect[0], rect[1],
                    #rect[2]-rect[0], rect[3]-rect[1],
                    #win32con.SWP_NOACTIVATE)
                #win32gui.SetWindowPos(hwnd,
                #    win32con.HWND_BOTTOM,
                #    -5000, -5000,
                #    rect[2]-rect[0], rect[3]-rect[1],
                #    win32con.SWP_HIDEWINDOW)

    shellHandlerPtr = (CFUNCTYPE(None, wintypes.HANDLE, c_uint, wintypes.HANDLE, c_uint, c_uint, c_uint, c_uint))(handle_shell)
    shellHook = windll.user32.SetWinEventHook(
        win32con.EVENT_OBJECT_LOCATIONCHANGE,
        win32con.EVENT_OBJECT_LOCATIONCHANGE,
        win32api.GetModuleHandle(None), shellHandlerPtr, 0, 0, win32con.WINEVENT_INCONTEXT)
    atexit.register(windll.user32.UnhookWinEvent, shellHook)"""
    
    while not pylewm.commands.stopped:
        msg = win32gui.GetMessage(None, 0, 0)
        win32gui.TranslateMessage(byref(msg))
        win32gui.DispatchMessage(byref(msg))
