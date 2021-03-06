import asyncio
from collections import namedtuple
from contextlib import contextmanager
import logging
import socket

import requests

import wifi

logging.basicConfig(level=logging.DEBUG)

_LOGGER = logging.getLogger(__name__)
CHANNELS = range(1, 12)
CONNECTED_WAIT_TIME = 5 * 60
RECEIVE_WAIT_TIME = 15
TRY_WAIT_TIME = 1 * 60
RUNNING = True
Network = namedtuple('Network', ['ssid', 'encryption'])

_LOGGER.info("Getting host name")
hostname = socket.gethostname()
_LOGGER.info("Hostname: %s", hostname)


async def start(interface):
    _LOGGER.debug("Starting...")
    while RUNNING:
        if await connected(interface):
            _LOGGER.debug("Already connected. Waiting %s seconds before checking again.",
                          CONNECTED_WAIT_TIME)
            await asyncio.sleep(CONNECTED_WAIT_TIME)
            continue

        _LOGGER.debug("Not connected. Looking for new WiFi credentials...")
        async with MonitorMode(interface) as monitor:
            for channel in CHANNELS:
                _LOGGER.debug("Setting channel to %s", channel)
                await monitor.set_channel(channel)

                wifi_info = await receive_wifi_info(interface)
                _LOGGER.debug("Received wifi info: %s", wifi_info)
                if wifi_info is not None:
                    ssid, password = wifi_info
                    _LOGGER.debug("Saving WiFi credentials")
                    await save_wifi_credentials(interface, ssid, password)
                    break

        if await has_wifi_credentials(interface):
            _LOGGER.debug("We have WiFi credentials, so we are trying to connect")
            result = await connect(interface)
            if result is not None:
                _LOGGER.debug("Connected (%s)!", result)
                _LOGGER.debug("Pinging gateway")
                requests.post("http://gateway.local:3210/ping",
                              data={'sensor': hostname})
                _LOGGER.debug("Restarting service")
                await restart_sensor_service()
            else:
                _LOGGER.debug("Not connected!")

        _LOGGER.debug("Waiting %s seconds before trying again", TRY_WAIT_TIME)
        await asyncio.sleep(TRY_WAIT_TIME)


def stop():
    global RUNNING
    RUNNING = False


async def connect(interface):
    return await wifi.connect(interface)


async def connected(interface):
    try:
        ip_address = await wifi.get_ip_address(interface)
        return ip_address is not None
    except Exception as e:
        _LOGGER.exception("Unable to determine if connected")
        return False


async def has_wifi_credentials(interface):
    return await wifi.interface_configured(interface)


async def save_wifi_credentials(interface, ssid, password):
    network = Network(ssid, 'wpa')
    await wifi.replace(interface, network, password)


async def receive_wifi_info(interface):
    _LOGGER.debug("Receiving WiFi Info")
    cmd = asyncio.create_subprocess_exec(
        '/usr/bin/python',
        '/root/unassociated_transfer/receive_wifi.py',
        interface,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    proc = await cmd

    try:
        stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(),
                                                          RECEIVE_WAIT_TIME)
        _LOGGER.debug("stdout: %s", stdout_data)
        _LOGGER.debug("stderr: %s", stderr_data)

        data = stdout_data.decode()
        if data == '':
            return None

        ssid, password = data.strip().split(':')

        return ssid, password
    except asyncio.TimeoutError:
        _LOGGER.debug("Timing out receiving WiFi info")
        return None


class MonitorMode():
    def __init__(self, interface):
        self.interface = interface

    async def set_channel(self, channel):
        cmd = asyncio.create_subprocess_exec(
            'iwconfig', self.interface, 'channel', str(channel),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        proc = await cmd
        stdout_data, stderr_data = await proc.communicate()

        _LOGGER.debug("stdout: %s", stdout_data)
        _LOGGER.debug("stderr: %s", stderr_data)

    async def __aenter__(self):
        _LOGGER.debug("Entering monitor mode")
        cmd = asyncio.create_subprocess_exec(
            'iwconfig', self.interface, 'mode', 'monitor',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        proc = await cmd
        stdout_data, stderr_data = await proc.communicate()

        _LOGGER.debug("stdout: %s", stdout_data)
        _LOGGER.debug("stderr: %s", stderr_data)

        return self

    async def __aexit__(self, exc_type, exc, tb):
        _LOGGER.debug("Exiting monitor mode")
        cmd = asyncio.create_subprocess_exec(
            'iwconfig', self.interface, 'mode', 'Managed',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        proc = await cmd
        stdout_data, stderr_data = await proc.communicate()

        _LOGGER.debug("stdout: %s", stdout_data)
        _LOGGER.debug("stderr: %s", stderr_data)
