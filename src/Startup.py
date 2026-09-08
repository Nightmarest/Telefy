from __future__ import annotations

import configparser
import multiprocessing
import os
import subprocess
import sys
import threading
import time
import webbrowser
from enum import Enum

# Support both `python -m src.Startup` and `cd src && python Startup.py`.
if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packaging import version
import requests
from PIL import Image
from colorama import init, Fore, Style
import psutil
from src import Helper
from src.CardRenderer import build_caption_html, render_track_card
from src.Spotify import spotify_callback
from src.Helper import ChannelID, Get_IconPath, Token, toggle_auto_start_windows
from src.TelegramRich import (
    EmojiPackManager,
    MosaicCache,
    TelegramRichClient,
    artist_stack_markdown,
    escape_link_url,
    escape_text,
)
from src.platform_utils import CACHE_DIR, CONFIG_PATH, IS_WINDOWS

if IS_WINDOWS:
    import winreg
    import pythoncom
    import pystray
    import win32con
    import win32console
    import win32gui
    from win32com.client import Dispatch
    from pystray import MenuItem as item
else:
    winreg = None  # type: ignore[assignment]
    pythoncom = None  # type: ignore[assignment]
    pystray = None  # type: ignore[assignment]
    win32con = None  # type: ignore[assignment]
    win32console = None  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]
    Dispatch = None  # type: ignore[assignment]
    item = None  # type: ignore[assignment]

config_file = str(CONFIG_PATH)
if not CONFIG_PATH.exists():
    Helper.CreateConfig()
cp = configparser.ConfigParser()
cp.read(config_file)
RInterval = cp['GENERAL']['RefreshInterval']
NotPlaying = cp['GENERAL']['NotPlaying']
OwnerID = cp['TG_CONF'].get('OwnerID', '0')
RenderMode = cp['GENERAL'].get('RenderMode', 'text').strip().lower()

Pause = 0
auto_start_windows = False
telegram = TelegramRichClient(Token)
emoji_manager: EmojiPackManager | None = None
preview_message_ids: list[int] = []


Current = "v2.0"
Repo = "https://github.com/Nightmarest/Telefy"


class LogType(Enum):
    Default = 0
    Notification = 1
    Error = 2
    Update_Status = 3

def log(text, type=LogType.Default):
    init()  # Инициализация colorama
    # Цвета текста
    red_text = Fore.RED
    yellow_text = Fore.YELLOW
    blue_text = Fore.CYAN
    reset_text = Style.RESET_ALL

    if type == LogType.Notification:
        message_color = yellow_text
    elif type == LogType.Error:
        message_color = red_text
    elif type == LogType.Update_Status:
        message_color = blue_text
    else:
        message_color = reset_text

    print(f"{red_text}[Telefy] -> {message_color}{text}{reset_text}")


def Publish(ChannelID):
    global Pause
    global preview_message_ids
    Data = spotify_callback()
    Track = Data['TrackID'] if Data is not None else None
    MID = None
    PhotoMID = None
    StaticMID = None
    ProgressMID = None
    try:
        while True:
            Data = spotify_callback()

            if RenderMode == "text":
                if Data is not None:
                    if MID is not None:
                        telegram.delete_message(ChannelID, MID)
                        MID = None

                    if PhotoMID is None or StaticMID is None or ProgressMID is None:
                        if MID is not None:
                            telegram.delete_message(ChannelID, MID)
                            MID = None
                        photo_message, static_message, progress_message = _send_text_track_bundle(ChannelID, Data)
                        PhotoMID = photo_message["message_id"]
                        StaticMID = static_message["message_id"]
                        ProgressMID = progress_message["message_id"]
                        Track = Data["TrackID"]
                        Pause = 0
                    else:
                        if Track == Data["TrackID"]:
                            try:
                                Message = _edit_progress_message(ChannelID, ProgressMID, Data)
                                ProgressMID = Message["message_id"]
                            except Exception:
                                pass
                            Pause = 0 if Data["State"] else 1
                        else:
                            telegram.delete_message(ChannelID, ProgressMID)
                            telegram.delete_message(ChannelID, StaticMID)
                            telegram.delete_message(ChannelID, PhotoMID)
                            photo_message, static_message, progress_message = _send_text_track_bundle(ChannelID, Data)
                            PhotoMID = photo_message["message_id"]
                            StaticMID = static_message["message_id"]
                            ProgressMID = progress_message["message_id"]
                            Track = Data["TrackID"]
                            Pause = 0
                else:
                    if PhotoMID is not None:
                        telegram.delete_message(ChannelID, ProgressMID)
                        telegram.delete_message(ChannelID, StaticMID)
                        telegram.delete_message(ChannelID, PhotoMID)
                        PhotoMID = None
                        StaticMID = None
                        ProgressMID = None
                    if MID is None or Pause != 2:
                        Message = telegram.send_message(chat_id=ChannelID, text=f"{NotPlaying}")
                        MID = Message["message_id"]
                        Pause = 2
                time.sleep(float(RInterval))
                continue

            if MID is None:
                if Data is not None:
                    Message = _send_track_message(ChannelID, Data)
                    MID = Message["message_id"]
                    Pause = 0

                else:
                    if Pause == 0 or Pause == 1:
                        Pause = 2
                        Message = telegram.send_message(chat_id=ChannelID, text=f"{NotPlaying}")
                        MID = Message["message_id"]


            else:
                if Data is not None:
                    if Data['State'] is False:
                        if Pause == 0:
                            try:
                                Message = _edit_track_message(ChannelID, MID, Data)
                                MID = Message["message_id"]
                            except Exception:
                                pass
                            Pause = 1
                    else:
                        if Track == Data['TrackID']:
                            try:
                                Message = _edit_track_message(ChannelID, MID, Data)
                                MID = Message["message_id"]
                            except Exception:
                                pass
                            Pause = 0

                        else:
                            telegram.delete_message(ChannelID, MID)
                            Track = Data['TrackID']
                            Message = _send_track_message(ChannelID, Data)
                            MID = Message["message_id"]
                            Pause = 0
                else:
                    if Pause == 0 or Pause == 1:
                        Pause = 2
                        telegram.delete_message(ChannelID, MID)
                        Message = telegram.send_message(chat_id=ChannelID, text=f"{NotPlaying}")
                        MID = Message["message_id"]

            time.sleep(float(RInterval))
    except Exception as e:
        print(f"Ошибка при передаче данных - {e}")
        pass


def _build_spotify_post(data: dict) -> str:
    return _build_text_post(data)


def _send_track_message(channel_id: str, data: dict) -> dict:
    if RenderMode == "card":
        caption = build_caption_html(data)
        card = render_track_card(data, telegram.session)
        return telegram.send_photo(
            chat_id=channel_id,
            photo=card,
            caption=caption,
            parse_mode="HTML",
        )
    payload = _build_text_caption_payload(data)
    return telegram.send_photo(
        chat_id=channel_id,
        photo=data["TA"],
        caption=payload["caption"],
        parse_mode="HTML",
    )


def _edit_track_message(channel_id: str, message_id: int, data: dict) -> dict:
    if RenderMode == "card":
        caption = build_caption_html(data)
        card = render_track_card(data, telegram.session)
        return telegram.edit_photo(
            chat_id=channel_id,
            message_id=message_id,
            photo=card,
            caption=caption,
            parse_mode="HTML",
        )
    payload = _build_text_caption_payload(data)
    return telegram.edit_photo_caption(
        chat_id=channel_id,
        message_id=message_id,
        caption=payload["caption"],
        parse_mode="HTML",
    )


def _build_text_post(data: dict) -> str:
    return _build_static_text_post(data)


def _build_static_text_post(data: dict) -> str:
    artist_stack = _build_artist_stack(data)
    artist_line_parts = []
    for artist in data["Artists"]:
        name = escape_text(artist["name"])
        url = artist.get("url") or ""
        if url:
            artist_line_parts.append(f"[{name}]({escape_link_url(url)})")
        else:
            artist_line_parts.append(name)
    parts = [
        f"*{escape_text(data['TrackName'])}*",
        " · ".join(artist_line_parts),
    ]
    if artist_stack:
        parts.extend(["", artist_stack])
    return "\n".join(parts)


def _build_progress_text(data: dict) -> str:
    return f"{data['TN']} / {data['TT']} {_build_progress_bar(data['ProgressMS'], data['DurationMS'])}"


def _build_artist_stack(data: dict) -> str | None:
    global emoji_manager
    try:
        owner_id = int(OwnerID)
    except (TypeError, ValueError):
        return None
    if owner_id <= 0:
        return None
    try:
        if emoji_manager is None:
            cache = MosaicCache(CACHE_DIR / "spotify_mosaic_cache.json")
            emoji_manager = EmojiPackManager(
                telegram,
                owner_id=owner_id,
                bot_username=_bot_username(),
                cache=cache,
            )
        return artist_stack_markdown(data["Artists"], telegram, emoji_manager)
    except Exception as e:
        log(f"Artist emoji mosaic disabled: {e}", LogType.Notification)
        return None


def _bot_username() -> str:
    me = telegram.call("getMe")
    return me.get("username", "telefy_bot")


def _build_progress_bar(progress_ms: int, duration_ms: int, width: int = 10) -> str:
    if duration_ms <= 0:
        return "▱" * width
    ratio = max(0.0, min(progress_ms / duration_ms, 1.0))
    filled = round(ratio * width)
    return "▰" * filled + "▱" * (width - filled)


def _build_text_caption_payload(data: dict) -> dict:
    return {"caption": ""}


def _send_text_track_bundle(channel_id: str, data: dict) -> tuple[dict, dict, dict]:
    global preview_message_ids
    photo_message = telegram.send_photo(chat_id=channel_id, photo=data["TA"])
    preview = telegram.send_rich_message(chat_id=int(OwnerID), markdown=_build_static_text_post(data))
    preview_message_ids.append(preview["message_id"])
    static_message = telegram.copy_message(channel_id, int(OwnerID), preview["message_id"])
    progress_message = telegram.send_message(chat_id=channel_id, text=_build_progress_text(data))
    try:
        telegram.delete_message(int(OwnerID), preview["message_id"])
        preview_message_ids.remove(preview["message_id"])
    except Exception:
        pass
    if len(preview_message_ids) > 20:
        stale = preview_message_ids.pop(0)
        try:
            telegram.delete_message(int(OwnerID), stale)
        except Exception:
            pass
    return photo_message, static_message, progress_message


def _edit_progress_message(channel_id: str, message_id: int, data: dict) -> dict:
    return telegram.call("editMessageText", {
        "chat_id": channel_id,
        "message_id": message_id,
        "text": _build_progress_text(data),
    })




def GetLastVersion(repoUrl):
    try:
        global Current
        response = requests.get(repoUrl + '/releases/latest', timeout=5)
        response.raise_for_status()
        latest_version = response.url.split('/')[-1]

        if version.parse(Current) < version.parse(latest_version):
            log(f"A new version has been released on GitHub. You are using - {Current}. A new version - {latest_version}, you can download it at {repoUrl + '/releases/tag/' + latest_version}",
                LogType.Notification)
        elif version.parse(Current) == version.parse(latest_version):
            log(f"You are using the latest version of the script!")
        else:
            log(f"You are using the beta version of the script", LogType.Notification)

    except requests.exceptions.RequestException as e:
        log(f"Error getting latest version: {e}", LogType.Error)
def Is_already_running():
    if not IS_WINDOWS:
        return False
    hwnd = win32gui.FindWindow(None, "Telefy")
    if hwnd:
        return True
    return False
def Check_run_by_startup():
    if not IS_WINDOWS:
        return
    # Если приложение запущено через автозагрузку, скрываем окно консоли сразу.
    # Если приложение запущено вручную, показываем окно консоли на 3 секунды и затем сворачиваем.
    if window:
        if '--run-through-startup' not in sys.argv:
            Show_Console_Permanent()
            log("Minimize to system tray in 3 seconds...")
            time.sleep(3)
        win32gui.ShowWindow(window, win32con.SW_HIDE)
    else:
        log("Console window not found", LogType.Error)
def Disable_close_button():
    if not IS_WINDOWS:
        return
    hwnd = win32console.GetConsoleWindow()
    if hwnd:
        hMenu = win32gui.GetSystemMenu(hwnd, False)
        if hMenu:
            win32gui.DeleteMenu(hMenu, win32con.SC_CLOSE, win32con.MF_BYCOMMAND)
def Is_run_by_exe():
    script_path = os.path.abspath(sys.argv[0])
    if script_path.endswith('.exe'):
        return True
    else:
        return False
def tray_click(icon, query):
    if not IS_WINDOWS:
        return
    action = str(query)
    if action == "GitHub":
        webbrowser.open("https://github.com/Nightmarest/Telefy",  new=2)
    elif action == "Exit":
        icon.stop()
        win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)


def toggle_auto_start_windows():
    if not IS_WINDOWS:
        log("Автозапуск через реестр доступен только в Windows", LogType.Notification)
        return
    global auto_start_windows
    auto_start_windows = not auto_start_windows
    log(f'Bool auto_start_windows set state: {auto_start_windows}')

    def create_shortcut(target, shortcut_path, description="", arguments=""):
        pythoncom.CoInitialize()  # Инициализируем COM библиотеки
        shell = Dispatch('WScript.Shell')  # Создаем объект для работы с ярлыками
        shortcut = shell.CreateShortcut(shortcut_path)  # Создаем ярлык
        shortcut.TargetPath = target  # Устанавливаем путь к исполняемому файлу
        shortcut.WorkingDirectory = os.path.dirname(target)  # Устанавливаем рабочую директорию
        shortcut.Description = description  # Устанавливаем описание ярлыка
        shortcut.Arguments = arguments
        shortcut.Save()  # Сохраняем ярлык

    def change_setting(
            tglle: bool):  # Выношу в отдельную функцию, чтобы иметь возможность запустить в отдельном потоке,
        if tglle:  # ДВА способа добавления в автозапуск. Первый через добавление программы в папку автостарта. Второй через изменение реестра. Оба не требуют админских прав.
            try:  # Автозапуск через добавление в папку автозапуска
                exe_path = os.path.abspath(sys.argv[0])  # Получаем абсолютный путь к текущему исполняемому файлу
                shortcut_path = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs',
                                             'Startup', 'Telefy.lnk')  # Определяем путь для ярлыка в автозагрузке
                create_shortcut(exe_path, shortcut_path,
                                arguments="--run-through-startup")  # Создаем ярлык в автозагрузке
            except:  # Автозапуск через изменение в реестре
                exe_path = f'"{os.path.abspath(sys.argv[0])}" --run-through-startup'
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run', 0,
                                     winreg.KEY_SET_VALUE)  # Открываем ключ реестра для автозапуска программ
                winreg.SetValueEx(key, 'Telefy', 0, winreg.REG_SZ,
                                  exe_path)  # Устанавливаем новый параметр в реестре с именем 'YaMusicRPC' и значением пути к исполняемому файлу
                winreg.CloseKey(key)  # Закрываем ключ реестра
        else:  # Удаляем оба метода
            # Удаляем ярлык из автозагрузки
            shortcut_path = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs',
                                         'Startup', 'Telefy.lnk')
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
            # Удаляем запись из реестра
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run', 0,
                                     winreg.KEY_ALL_ACCESS)
                winreg.DeleteValue(key, 'Telefy')
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass

    threading.Thread(target=change_setting,
                     args=[auto_start_windows]).start()  # Запускаем в отдельном потоке для оптимизации


def create_tray_icon():
    if not IS_WINDOWS:
        return None
    tray_image = Image.open(Get_IconPath())

    icon = pystray.Icon("Telefy", tray_image, "Telefy", menu=pystray.Menu(
        pystray.MenuItem("Hide/Show Console", toggle_console, default=True),
        pystray.MenuItem('Start with Windows', toggle_auto_start_windows, checked=lambda item: auto_start_windows),
        pystray.MenuItem("GitHub", tray_click),
        pystray.MenuItem("Exit", tray_click)
    ))
    return icon
def Run_by_startup_without_conhost():
    if not IS_WINDOWS:
        return
    # Функция для автозагрузки без лаунчера (Windows 11), скрывает окно консоли при запуске через автозагрузку.
    window = win32console.GetConsoleWindow()
    if window:
        if '--run-through-startup' in sys.argv:
            win32gui.ShowWindow(window, win32con.SW_HIDE)
    else:
        print("Console window not found")
def Show_Console_Permanent():
    if not IS_WINDOWS:
        return
    win32gui.ShowWindow(window, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(window)
def Is_windows_11():
    if not IS_WINDOWS:
        return False
    return sys.getwindowsversion().build >= 22000
def Set_ConsoleMode():
    if not IS_WINDOWS:
        return
    hStdin = win32console.GetStdHandle(win32console.STD_INPUT_HANDLE)
    mode = hStdin.GetConsoleMode()
    # Отключить ENABLE_QUICK_EDIT_MODE, чтобы запретить выделение текста
    new_mode = mode & ~0x0040
    hStdin.SetConsoleMode(new_mode)
def tray_thread(icon):
    if not IS_WINDOWS or icon is None:
        return
    icon.run()
def toggle_console():
    if not IS_WINDOWS:
        return
    if win32gui.IsWindowVisible(window):
        win32gui.ShowWindow(window, win32con.SW_HIDE)
    else:
        Show_Console_Permanent()
def WaitAndExit():
        if not IS_WINDOWS:
            sys.exit(0)
        win32gui.ShowWindow(window, win32con.SW_SHOW)
        win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
        sys.exit(0)
def on_exit(icon, item):
    icon.stop()
    sys.exit()

def setup(icon):
    icon.visible = True

def main():
    Publish(ChannelID)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    try:
        if IS_WINDOWS and Is_run_by_exe():
            Set_ConsoleMode()
            print("Launched. Check the actual version...")
            GetLastVersion(Repo)
            spotify_callback()
            mainMenu = create_tray_icon()
            if mainMenu is not None:
                icon_thread = threading.Thread(target=tray_thread, args=(mainMenu,))
                icon_thread.daemon = True
                icon_thread.start()

                # Получение окна консоли
                window = win32console.GetConsoleWindow()

                if Is_already_running():
                    print("Telefy is already running.")
                    Show_Console_Permanent()
                    WaitAndExit()

                # Установка заголовка окна консоли
                win32console.SetConsoleTitle("Telefy")

                # Отключение кнопки закрытия консоли
                Disable_close_button()
                Check_run_by_startup()
        else:
            print("Running in Linux/macOS mode.")
        try:
            main()
        finally:
            telegram.close()

    except KeyboardInterrupt:
        log("Keyboard interrupt received, stopping...")
        sys.exit(0)
