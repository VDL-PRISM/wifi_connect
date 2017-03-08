import argparse
import asyncio
import functools
import logging
from logging import handlers
import signal

from aiohttp import web

from server import app
import wifi

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s:%(threadName)s:%(levelname)s:'
                           '%(name)s:%(message)s',
                    handlers=[
                        handlers.TimedRotatingFileHandler(
                            'prisms-wifi.log', when='midnight', backupCount=7,
                            delay=True),
                        logging.StreamHandler()])


def ask_exit(signame):
    print("got signal %s: exit" % signame)
    loop.stop()


parser = argparse.ArgumentParser(
    description='Creates a server to set up wireless SSID and passkey')
parser.add_argument('interface', help='Wireless interface to use')
args = parser.parse_args()
app.interface = args.interface

loop = asyncio.get_event_loop()
for signame in ('SIGINT', 'SIGTERM'):
    loop.add_signal_handler(getattr(signal, signame),
                            functools.partial(ask_exit, signame))

# Make sure everything is configured correctly
loop = asyncio.get_event_loop()
loop.run_until_complete(wifi.update_interfaces())

try:
    # Run web app
    web.run_app(app, port=3210)
finally:
    loop.close()
