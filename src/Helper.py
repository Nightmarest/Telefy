import configparser
import os
import telebot

config_file = 'config.ini'
cp = configparser.ConfigParser()


def CreateConfig():
    print(f'Файл конфигурации {config_file} не найден, будем создавать')
    cp['SP_AUTH'] = {
        'CLIENT_ID': 'YOUR_CLIENT_ID',
        'CLIENT_SECRET': 'YOUR_CLIENT_SECRET',
    }
    cp['TG_CONF'] = {
        'BotToken': 'YourToken',
        'ChannelID': 'YourChannelID',
    }
    cp['GENERAL'] = {
        'NotPlaying': 'Какая досада, сейчас ничего не играет!',
        'RefreshInterval': '3',
    }
    with open(config_file, 'w') as f:
        cp.write(f)
    print(f'Файл конфигурации {config_file} успешно создан. Введите все данные для корректной работы.')
    return
if not os.path.exists(config_file):
    CreateConfig()

cp.read(config_file)
Token = cp['TG_CONF']['BotToken']
ChannelID = cp['TG_CONF']['ChannelID']
bot = telebot.TeleBot(Token, parse_mode='HTML')

