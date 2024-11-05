import configparser
import multiprocessing
import os
import subprocess
import sys
import threading
import time
import webbrowser
import winreg
from enum import Enum
from packaging import version
import pythoncom
import requests
from PIL import Image
from colorama import init, Fore, Style
import pystray
import win32con
import win32console
import win32gui
from win32com.client import Dispatch
import psutil
from src import Helper
from src.Spotify import spotify_callback
from src.Helper import bot, ChannelID, Get_IconPath, toggle_auto_start_windows
from pystray import MenuItem as item

config_file = 'config.ini'
if not os.path.exists(config_file):
    Helper.CreateConfig()
cp = configparser.ConfigParser()
cp.read(config_file)
RInterval = cp['GENERAL']['RefreshInterval']
NotPlaying = cp['GENERAL']['NotPlaying']

Pause = 0
auto_start_windows = False


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
    Data = spotify_callback()
    if Data is not None:
        Track = Data['AT']
    else:
        pass
    MID = None
    try:
        while True:
            Data = spotify_callback()

            if MID is None:
                if Data is not None:
                    Text = f"""<b>{Data['AT']} [ {Data['TN']} / {Data['TT']} ]</b>"""
                    Message = bot.send_photo(chat_id=ChannelID, photo=Data['TA'], caption=Text)
                    MID = Message.message_id
                    Pause = 0

                else:
                    if Pause == 0 or Pause == 1:
                        Pause = 2
                        Message = bot.send_message(chat_id=ChannelID, text=f"{NotPlaying}")
                        MID = Message.message_id


            else:
                if Data is not None:
                    if Data['State'] is False:
                        if Pause == 0:
                            Text = f"""<b>[PAUSED] {Data['AT']} [ {Data['TN']} / {Data['TT']} ]</b>"""
                            try:
                                Message = bot.edit_message_caption(chat_id=ChannelID, message_id=MID, caption=Text)
                            except Exception:
                                pass
                            Pause = 1
                    else:
                        if Track == Data['AT']:
                            Text = f"""<b>{Data['AT']} [ {Data['TN']} / {Data['TT']} ]</b>"""
                            try:
                                Message = bot.edit_message_caption(chat_id=ChannelID, message_id=MID, caption=Text)
                            except Exception:
                                pass
                            MID = Message.message_id
                            Pause = 0

                        else:
                            bot.delete_message(ChannelID, MID)
                            Track = Data['AT']
                            Text = f"""<b>{Data['AT']} [ {Data['TN']} / {Data['TT']} ]</b>"""
                            Message = bot.send_photo(chat_id=ChannelID, photo=Data['TA'], caption=Text)
                            MID = Message.message_id
                            Pause = 0
                else:
                    if Pause == 0 or Pause == 1:
                        Pause = 2
                        bot.delete_message(ChannelID, MID)
                        Message = bot.send_message(chat_id=ChannelID, text=f"{NotPlaying}")
                        MID = Message.message_id

            time.sleep(float(RInterval))
    except Exception as e:
        print(f"Ошибка при передаче данных - {e}")
        pass


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
    hwnd = win32gui.FindWindow(None, "Telefy")
    if hwnd:
        return True
    return False
def Check_run_by_startup():
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
    match str(query):
        case "GitHub":
            webbrowser.open("https://github.com/Nightmarest/Telefy",  new=2)

        case "Exit":
            icon.stop()
            win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)


def toggle_auto_start_windows():
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
    tray_image = Image.open(Get_IconPath())

    icon = pystray.Icon("Telefy", tray_image, "Telefy", menu=pystray.Menu(
        pystray.MenuItem("Hide/Show Console", toggle_console, default=True),
        pystray.MenuItem('Start with Windows', toggle_auto_start_windows, checked=lambda item: auto_start_windows),
        pystray.MenuItem("GitHub", tray_click),
        pystray.MenuItem("Exit", tray_click)
    ))
    return icon
def Run_by_startup_without_conhost():
    # Функция для автозагрузки без лаунчера (Windows 11), скрывает окно консоли при запуске через автозагрузку.
    window = win32console.GetConsoleWindow()
    if window:
        if '--run-through-startup' in sys.argv:
            win32gui.ShowWindow(window, win32con.SW_HIDE)
    else:
        print("Console window not found")
def Show_Console_Permanent():
    win32gui.ShowWindow(window, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(window)
def Is_windows_11():
    return sys.getwindowsversion().build >= 22000
def Set_ConsoleMode():
    hStdin = win32console.GetStdHandle(win32console.STD_INPUT_HANDLE)
    mode = hStdin.GetConsoleMode()
    # Отключить ENABLE_QUICK_EDIT_MODE, чтобы запретить выделение текста
    new_mode = mode & ~0x0040
    hStdin.SetConsoleMode(new_mode)
def tray_thread(icon):
    icon.run()
def toggle_console():
    if win32gui.IsWindowVisible(window):
        win32gui.ShowWindow(window, win32con.SW_HIDE)
    else:
        Show_Console_Permanent()
def WaitAndExit():
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
        if Is_run_by_exe():
            Set_ConsoleMode()
            print("Launched. Check the actual version...")
            GetLastVersion(Repo)
            spotify_callback()
            mainMenu = create_tray_icon()
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
            pass
        main()

    except KeyboardInterrupt:
        log("Keyboard interrupt received, stopping...")
        sys.exit(0)