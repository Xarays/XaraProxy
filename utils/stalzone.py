# stalzone
import os
import winreg

def find_stalzone_paths():
    candidates = []
    try:
        steam_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path = winreg.QueryValueEx(steam_key, "SteamPath")[0]
        winreg.CloseKey(steam_key)
        library_folders = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
        if os.path.exists(library_folders):
            with open(library_folders, "r", encoding="utf-8") as f:
                content = f.read()
            for line in content.splitlines():
                if '"path"' in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        path = parts[3].strip()
                        common = os.path.join(path, "steamapps", "common")
                        if os.path.exists(common):
                            for name in ("STALZONE", "STALCRAFT"):
                                p = os.path.join(common, name)
                                if os.path.isdir(p):
                                    candidates.append(p)
    except Exception:
        pass

    extra_roots = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "EXBO", "STALZONE"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "EXBO", "STALZONE"),
        os.path.join(os.environ.get("LocalAppData", ""), "EXBO", "STALZONE"),
        os.path.join(os.environ.get("LocalAppData", ""), "VKPlay", "games", "STALZONE"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "VKPlay", "STALZONE"),
    ]
    for p in extra_roots:
        if os.path.isdir(p):
            candidates.append(p)

    seen, unique = set(), []
    for p in candidates:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique