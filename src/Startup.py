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


def Publish(ChannelID):
    Data = spotify_callback()
    if Data is not None:
        Track = Data['AT']
    else:
        pass
    MID = None

    while True:
        Data = spotify_callback()

        if MID is None:
            if Data is not None:
                Text = f"""<b>{Data['AT']} [ {Data['TN']} / {Data['TT']} ]</b>"""
                Message = bot.send_photo(chat_id=ChannelID, photo=Data['TA'], caption=Text)
                MID = Message.message_id
            else:
                bot.send_message(chat_id=ChannelID, text=f"{NotPlaying}")

        else:
            if Data is not None:
                if Track == Data['AT']:

                    Text = f"""<b>{Data['AT']} [ {Data['TN']} / {Data['TT']} ]</b>"""
                    try:
                        Message = bot.edit_message_caption(chat_id=ChannelID, message_id=MID, caption=Text)
                    except Exception:
                        pass
                    MID = Message.message_id
                else:
                    bot.delete_message(ChannelID, MID)
                    Track = Data['AT']
                    Text = f"""<b>{Data['AT']} [ {Data['TN']} / {Data['TT']} ]</b>"""
                    Message = bot.send_photo(chat_id=ChannelID, photo=Data['TA'], caption=Text)
                    MID = Message.message_id
        time.sleep(float(RInterval))

def main():
    print("!")
    Publish(ChannelID)


if __name__ == "__main__":
    main()