import configparser
import os
import time
from src import Helper
from src.Spotify import spotify_callback
from src.Helper import bot, ChannelID

config_file = 'config.ini'
if not os.path.exists(config_file):
    Helper.CreateConfig()
cp = configparser.ConfigParser()
cp.read(config_file)
RInterval = cp['GENERAL']['RefreshInterval']
NotPlaying = cp['GENERAL']['NotPlaying']

Pause = 0
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

def main():
    print("!")
    Publish(ChannelID)


if __name__ == "__main__":
    main()