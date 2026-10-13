"""Run `python -m src --mode website` without importing Telegram or Windows UI."""
import argparse
import configparser


def main():
    parser=argparse.ArgumentParser(description='Telefy music activity')
    parser.add_argument('--mode',choices=('website','telegram'))
    parser.add_argument('--config',default='config.ini')
    args=parser.parse_args()
    config=configparser.ConfigParser(interpolation=None);config.read(args.config)
    mode=args.mode or config.get('GENERAL','Mode',fallback='website').lower()
    if mode=='website':
        from .NowPlaying import run
        run(args.config)
    elif mode=='telegram':
        if args.config!='config.ini':parser.error('Legacy Telegram mode uses config.ini.')
        import runpy
        runpy.run_module("src.Startup",run_name="__main__")
    else:parser.error('GENERAL Mode must be website or telegram.')

if __name__=='__main__':main()
