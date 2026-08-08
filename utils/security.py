# security
import ctypes
import subprocess
import uuid
from ctypes import POINTER, Structure, c_ulong, c_ushort, c_byte, c_wchar_p, c_void_p
from resources.constants import CREATE_NO_WINDOW

class GUID(Structure):
    _fields_ = [
        ("Data1", c_ulong),
        ("Data2", c_ushort),
        ("Data3", c_ushort),
        ("Data4", c_byte * 8),
    ]
    def __init__(self, guid_string: str):
        u = uuid.UUID(guid_string)
        self.Data1 = u.int >> 96
        self.Data2 = (u.int >> 80) & 0xFFFF
        self.Data3 = (u.int >> 64) & 0xFFFF
        data4_bytes = u.bytes[-8:]
        for i in range(8):
            self.Data4[i] = data4_bytes[i]

WINTRUST_ACTION_GENERIC_VERIFY_V2 = GUID("{00AAC56B-CD44-11d0-8CC2-00C04FC295EE}")
WTD_CHOICE_FILE = 1
WTD_REVOCATION_CHECK_NONE = 0
WTD_STATEACTION_IGNORE = 0
WTD_UI_NONE = 2

class WINTRUST_FILE_INFO(Structure):
    _fields_ = [
        ("cbStruct", c_ulong),
        ("pcwszFilePath", c_wchar_p),
        ("hFile", c_void_p),
        ("pgKnownSubject", c_void_p),
    ]

class WINTRUST_DATA(Structure):
    _fields_ = [
        ("cbStruct", c_ulong),
        ("pPolicyCallbackData", c_void_p),
        ("pSIPClientData", c_void_p),
        ("dwUIChoice", c_ulong),
        ("fdwRevocationChecks", c_ulong),
        ("dwUnionChoice", c_ulong),
        ("pFile", POINTER(WINTRUST_FILE_INFO)),
        ("dwStateAction", c_ulong),
        ("hWVTStateData", c_void_p),
        ("pwszURLReference", c_void_p),
        ("dwProvFlags", c_ulong),
        ("dwUIContext", c_ulong),
        ("pSignatureSettings", c_void_p),
    ]

def verify_file_signature(filepath: str) -> bool:
    try:
        file_info = WINTRUST_FILE_INFO(
            cbStruct=ctypes.sizeof(WINTRUST_FILE_INFO),
            pcwszFilePath=filepath, hFile=None, pgKnownSubject=None,
        )
        wintrust_data = WINTRUST_DATA(
            cbStruct=ctypes.sizeof(WINTRUST_DATA),
            pPolicyCallbackData=None, pSIPClientData=None,
            dwUIChoice=WTD_UI_NONE, fdwRevocationChecks=WTD_REVOCATION_CHECK_NONE,
            dwUnionChoice=WTD_CHOICE_FILE, pFile=ctypes.pointer(file_info),
            dwStateAction=WTD_STATEACTION_IGNORE, hWVTStateData=None,
            pwszURLReference=None, dwProvFlags=0, dwUIContext=0, pSignatureSettings=None,
        )
        result = ctypes.windll.wintrust.WinVerifyTrust(
            None, ctypes.byref(WINTRUST_ACTION_GENERIC_VERIFY_V2), ctypes.byref(wintrust_data)
        )
        return result == 0
    except Exception:
        return False

KILL_SWITCH_RULE_NAME = "XaraProxy_KillSwitch_Block"

def apply_kill_switch_rule() -> None:
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={KILL_SWITCH_RULE_NAME}", "dir=out", "action=block", "enable=yes"],
            shell=False, check=False, creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass

def remove_kill_switch_rule() -> None:
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={KILL_SWITCH_RULE_NAME}"],
            shell=False, check=False, creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass