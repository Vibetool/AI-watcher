import argparse
import configparser
import json
import os
import sys
import time

CONFIG_FILENAME = 'config.ini'


def get_config():
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(__file__), CONFIG_FILENAME)
    if not os.path.exists(config_path):
        return {}

    config.read(config_path)
    if 'camera' not in config:
        return {}
    return config['camera']


def cmd_info(cam):
    try:
        resp = cam.devicemgmt.GetDeviceInformation()
        return {
            'Manufacturer': getattr(resp, 'Manufacturer', ''),
            'Model': getattr(resp, 'Model', ''),
            'FirmwareVersion': getattr(resp, 'FirmwareVersion', ''),
            'SerialNumber': getattr(resp, 'SerialNumber', ''),
            'HardwareId': getattr(resp, 'HardwareId', ''),
        }
    except Exception as exc:
        return {'error': str(exc)}


def get_media_profile(cam):
    media = cam.create_media_service()
    profiles = media.GetProfiles()
    if not profiles:
        raise Exception('No media profiles found on device')
    return media, profiles[0]


def cmd_stream_uri(cam):
    media, profile = get_media_profile(cam)
    req = media.create_type('GetStreamUri')
    req.ProfileToken = profile.token
    req.StreamSetup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
    res = media.GetStreamUri(req)
    return {'StreamUri': res.Uri}


def cmd_snapshot_uri(cam):
    media, profile = get_media_profile(cam)
    req = media.create_type('GetSnapshotUri')
    req.ProfileToken = profile.token
    res = media.GetSnapshotUri(req)
    return {'SnapshotUri': res.Uri}


def cmd_ptz(cam, act, duration=0.5):
    media, profile = get_media_profile(cam)

    try:
        ptz = cam.create_ptz_service()
    except Exception:
        return {'error': 'Camera does not support PTZ or PTZ service could not be initialized'}

    if act == 'stop':
        ptz.Stop({'ProfileToken': profile.token, 'PanTilt': True, 'Zoom': True})
        return {'status': 'stopped'}

    if act == 'home':
        try:
            req = ptz.create_type('GotoHomePosition')
            req.ProfileToken = profile.token
            ptz.GotoHomePosition(req)
            return {'status': 'homed'}
        except Exception as exc:
            return {'error': f'GotoHomePosition failed: {str(exc)}'}

    req = ptz.create_type('ContinuousMove')
    req.ProfileToken = profile.token

    status = ptz.GetStatus({'ProfileToken': profile.token})
    req.Velocity = status.Position

    pan, tilt, zoom = 0.0, 0.0, 0.0
    if act == 'left':
        pan = -1.0
    elif act == 'right':
        pan = 1.0
    elif act == 'up':
        tilt = 1.0
    elif act == 'down':
        tilt = -1.0
    elif act == 'zoomin':
        zoom = 1.0
    elif act == 'zoomout':
        zoom = -1.0

    if hasattr(req.Velocity, 'PanTilt') and req.Velocity.PanTilt is not None:
        req.Velocity.PanTilt.x = pan
        req.Velocity.PanTilt.y = tilt
    if hasattr(req.Velocity, 'Zoom') and req.Velocity.Zoom is not None:
        req.Velocity.Zoom.x = zoom

    ptz.ContinuousMove(req)

    if duration > 0:
        time.sleep(duration)
        ptz.Stop({'ProfileToken': profile.token, 'PanTilt': True, 'Zoom': True})
        return {'status': 'moved_and_stopped', 'action': act, 'duration': duration}

    return {'status': 'moving', 'action': act}


def main():
    parser = argparse.ArgumentParser(description='ONVIF Camera Control')
    parser.add_argument('command', choices=['info', 'stream_uri', 'snapshot_uri', 'ptz'], help='Command to run')
    parser.add_argument('--act', choices=['up', 'down', 'left', 'right', 'zoomin', 'zoomout', 'home', 'stop'], help='PTZ action')
    parser.add_argument('--duration', type=float, default=0.5, help='PTZ move duration before auto-stop')

    overrides = parser.add_argument_group('Overrides')
    overrides.add_argument('--ip', help='Camera IP')
    overrides.add_argument('--port', type=int, help='Camera port')
    overrides.add_argument('--user', help='Username')
    overrides.add_argument('--password', help='Password')

    parsed = parser.parse_args()

    conf = get_config()
    ip = parsed.ip or conf.get('ip')
    user = parsed.user or conf.get('username')
    password = parsed.password or conf.get('password')

    try:
        port = parsed.port or int(conf.get('port', 80))
    except ValueError:
        print(json.dumps({'ok': False, 'error': 'Invalid port value in scripts/config.ini'}))
        sys.exit(1)

    if not ip or not user or not password:
        print(
            json.dumps(
                {
                    'ok': False,
                    'error': 'Missing camera configuration. Run the setup wizard first or provide --ip, --user, and --password.',
                }
            )
        )
        sys.exit(1)

    try:
        import onvif

        wsdl_dir = os.path.join(os.path.dirname(os.path.dirname(onvif.__file__)), 'wsdl')
        cam = onvif.ONVIFCamera(ip, port, user, password, wsdl_dir)

        if parsed.command == 'info':
            result = cmd_info(cam)
        elif parsed.command == 'stream_uri':
            result = cmd_stream_uri(cam)
        elif parsed.command == 'snapshot_uri':
            result = cmd_snapshot_uri(cam)
        elif parsed.command == 'ptz':
            if not parsed.act:
                result = {'error': 'Missing --act argument for PTZ command'}
            else:
                result = cmd_ptz(cam, parsed.act, parsed.duration)
        else:
            result = {'error': 'Command not yet implemented'}

        print(json.dumps({'ok': 'error' not in result, 'result': result}, indent=2))

    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
        sys.exit(1)


if __name__ == '__main__':
    main()
