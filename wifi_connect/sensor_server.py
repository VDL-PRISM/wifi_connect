import asyncio
import logging

from aiohttp import web
import socketio

import utils
import wifi


_LOGGER = logging.getLogger(__name__)

sio = socketio.AsyncServer()
app = web.Application()
sio.attach(app)


async def index(request):
    """Serve the client-side application."""
    with open('static/sensor-index.html') as f:
        return web.Response(text=f.read(), content_type='text/html')


@sio.on('wifi-status')
async def handle_wifi_status(sid):
    try:
        message = await wifi.is_connected(app.interface)
        await sio.emit('wifi-status', {'message': message})
    except Exception:
        _LOGGER.exception("Exception occurred while getting WiFi status")
        await sio.emit('wifi-get', {'message': 'Error occurred'})


@sio.on('wifi-get')
async def handle_wifi_get(sid):
    try:
        ssid = await wifi.get_ssid(app.interface)

        if ssid is None:
            await sio.emit('wifi-get', {'ssid': ''})
        else:
            await sio.emit('wifi-get', {'ssid': ssid})
    except Exception:
        _LOGGER.exception("Exception occurred while getting SSID")
        await sio.emit('wifi-get', {'ssid': ''})


@sio.on('wifi-scan')
async def handle_wifi_scan(sid):
    try:
        networks = await wifi.scan(app.interface)
        networks = ((n.ssid, n.encryption) for n in networks)
        networks = sorted(networks, key=lambda x: x[0].lower())
        await sio.emit('wifi-scan', networks)
    except Exception:
        _LOGGER.exception("Exception occurred while scanning")
        await sio.emit('wifi-scan', [('Error occurred while scanning.', '')])


@sio.on('wifi-update')
async def handle_wifi_update(sid, data):
    if 'ssid' not in data or len(data['ssid']) == 0:
        await sio.emit('wifi-update',
                       {'message': 'Network name must be provided'})
        return

    if 'password' not in data or len(data['password']) == 0:
        await sio.emit('wifi-update', {'message': 'Password must be provided'})
        return

    ssid = data['ssid']
    password = data['password']

    try:
        await sio.emit('wifi-update', {'message': 'Looking for network...'})
        networks = await wifi.scan(app.interface)
        networks = [n for n in networks if n.ssid == ssid]
        await asyncio.sleep(.5)
        if len(networks) == 0:
            await sio.emit('wifi-update',
                           {'message': 'No network named {}'.format(ssid)})
            return
    except Exception:
        _LOGGER.exception("Exception occurred while scanning")
        await sio.emit('wifi-update',
                       {'message': 'Error occurred while scanning.'})
        return

    # Filter out networks that have incompatible security
    networks = [n for n in networks
                if n.encryption and n.encryption.startswith('wpa')]
    if len(networks) == 0:
        _LOGGER.warning("No networks that have correct encryption")
        await sio.emit('wifi-update',
                       {'message': 'Select network with WPA or WPA2'
                                   'security'})
        return

    try:
        await sio.emit('wifi-update',
                       {'message': 'Saving network name and password...'})
        await wifi.replace(app.interface, networks[0], password)
        await asyncio.sleep(.5)
    except NotImplementedError:
        _LOGGER.exception("Unknown security protocol was used")
        await sio.emit('wifi-update',
                       {'message': 'Only select WPA or WPA2 security'})
        return
    except Exception:
        _LOGGER.exception(
            "Exception occurred while setting new ssid and password")
        await sio.emit('wifi-update',
                       {'message': 'Error occurred while setting new SSID and'
                                   ' password.'})
        return

    await sio.emit('wifi-status', {'message': 'Not Connected'})
    await sio.emit('wifi-update', {'message': 'Connecting...'})
    await asyncio.sleep(.5)

    try:
        ip_address = await wifi.connect(app.interface)

        if not ip_address:
            await sio.emit('wifi-update',
                           {'message': 'Not connected! Make sure to check the'
                                       ' password.'})
        else:
            await sio.emit('wifi-update', {'message': 'Connected!'})
    except Exception:
        _LOGGER.exception("Exception occurred while connecting")
        await sio.emit('wifi-update',
                       {'message': 'Error occurred while connecting.'})
        await handle_wifi_status(None)
        return

    await handle_wifi_status(None)

    result = await utils.restart_sensor_service()
    if not result:
        await sio.emit('wifi-update',
                       {'message': 'Connected! An error occurred while '
                                   'restarting sensor service. Please restart'
                                   ' device.'})


app.router.add_static('/static', 'static')
app.router.add_get('/', index)
