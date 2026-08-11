import configparser
import os
import sys

import telebot
from PIL import Image, ImageDraw

from src.platform_utils import ASSETS_DIR, CONFIG_PATH, IS_WINDOWS

if IS_WINDOWS:
    import pystray
    import win32gui
else:
    pystray = None  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]

config_file = str(CONFIG_PATH)
cp = configparser.ConfigParser()


def CreateConfig():
    print(f'Файл конфигурации {config_file} не найден, будем создавать')
    cp['SP_AUTH'] = {
        'CLIENT_ID': 'YOUR_CLIENT_ID',
        'CLIENT_SECRET': 'YOUR_CLIENT_SECRET',
        'CALLBACK_URL': 'YOUR_CALLBACK_URL'
    }
    cp['TG_CONF'] = {
        'BotToken': 'YourToken',
        'ChannelID': 'YourChannelID',
    }
    cp['GENERAL'] = {
        'NotPlaying': 'Oh no, where my music???',
        'RefreshInterval': '3',
    }
    with open(config_file, 'w') as f:
        cp.write(f)
    print(f'Файл конфигурации {config_file} успешно создан. Введите все данные для корректной работы.')
    return
if not os.path.exists(config_file):
    CreateConfig()

def toggle_auto_start_windows():
    global auto_start_windows
    auto_start_windows = not auto_start_windows
def Get_IconPath():
    try:
        # Установка пути к ресурсам
        if getattr(sys, 'frozen', False):  # Запуск с помощью PyInstaller
            resources_path = sys._MEIPASS
        else:
            resources_path = str(ASSETS_DIR)

        if getattr(sys, 'frozen', False):
            return os.path.join(resources_path, 'assets', 'Telefy.ico')
        return os.path.join(resources_path, 'Telefy.ico')
    except Exception:
        return None



cp.read(config_file)
Token = cp['TG_CONF']['BotToken']
ChannelID = cp['TG_CONF']['ChannelID']
bot = telebot.TeleBot(Token, parse_mode='HTML')

