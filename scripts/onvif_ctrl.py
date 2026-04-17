import argparse
import configparser
import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import HTTPBasicAuthHandler, HTTPPasswordMgrWithDefaultRealm, Request, build_opener

CONFIG_FILENAME = 'config.ini'
PTZ_LOCK_FILE = '/tmp/onvif_camera_ptz.lock'
PTZ_STATE_FILE = '/tmp/onvif_camera_ptz_state.json'
PTZ_LOCK_TIMEOUT_SECONDS = 10.0
PTZ_COOLDOWN_SECONDS = 0.8
PTZ_RETRY_DELAY_SECONDS = 0.6
DEFAULT_CAPTURE_OUTPUT = '/tmp/snapshot.jpg'
DEFAULT_CAPTURE_MAX_WIDTH = 1280
DEFAULT_CAPTURE_QUALITY = 85
DEFAULT_HTTP_TIMEOUT_SECONDS = 10


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


@contextlib.contextmanager
def ptz_lock(timeout=PTZ_LOCK_TIMEOUT_SECONDS):
    with open(PTZ_LOCK_FILE, 'w', encoding='utf-8') as handle:
        deadline = time.time() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    raise TimeoutError('Timed out waiting for PTZ lock. Another PTZ command is still running.')
                time.sleep(0.1)

        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_ptz_state():
    if not os.path.exists(PTZ_STATE_FILE):
        return {}

    try:
        with open(PTZ_STATE_FILE, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return {}


def save_ptz_state(action):
    state = {
        'last_action': action,
        'last_finished_at': time.time(),
    }
    with open(PTZ_STATE_FILE, 'w', encoding='utf-8') as handle:
        json.dump(state, handle)


def enforce_ptz_cooldown(min_interval=PTZ_COOLDOWN_SECONDS):
    state = load_ptz_state()
    last_finished_at = state.get('last_finished_at')
    if not last_finished_at:
        return

    elapsed = time.time() - float(last_finished_at)
    remaining = min_interval - elapsed
    if remaining > 0:
        time.sleep(remaining)


def safe_ptz_stop(ptz, profile_token):
    try:
        ptz.Stop({'ProfileToken': profile_token, 'PanTilt': True, 'Zoom': True})
        return True
    except Exception:
        return False


def is_transient_ptz_error(exc):
    text = str(exc)
    return 'Internal Server Error' in text or '500' in text


def build_ptz_move_request(ptz, profile_token, act):
    req = ptz.create_type('ContinuousMove')
    req.ProfileToken = profile_token

    status = ptz.GetStatus({'ProfileToken': profile_token})
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

    return req


def cmd_ptz(cam, act, duration=0.5):
    media, profile = get_media_profile(cam)

    try:
        ptz = cam.create_ptz_service()
    except Exception:
        return {'error': 'Camera does not support PTZ or PTZ service could not be initialized'}

    profile_token = profile.token

    try:
        with ptz_lock():
            if act == 'stop':
                stopped = safe_ptz_stop(ptz, profile_token)
                save_ptz_state('stop')
                return {'status': 'stopped' if stopped else 'stop_requested'}

            enforce_ptz_cooldown()
            safe_ptz_stop(ptz, profile_token)

            if act == 'home':
                try:
                    req = ptz.create_type('GotoHomePosition')
                    req.ProfileToken = profile_token
                    ptz.GotoHomePosition(req)
                    save_ptz_state('home')
                    return {'status': 'homed'}
                except Exception as exc:
                    return {'error': f'GotoHomePosition failed: {str(exc)}'}

            if duration <= 0:
                return {'error': 'For safety, PTZ move duration must be greater than 0 so the camera can auto-stop.'}

            req = build_ptz_move_request(ptz, profile_token, act)
            used_retry = False
            move_started = False

            try:
                try:
                    ptz.ContinuousMove(req)
                except Exception as exc:
                    if not is_transient_ptz_error(exc):
                        raise
                    safe_ptz_stop(ptz, profile_token)
                    time.sleep(PTZ_RETRY_DELAY_SECONDS)
                    ptz.ContinuousMove(req)
                    used_retry = True

                move_started = True
                time.sleep(duration)
                return {
                    'status': 'moved_and_stopped',
                    'action': act,
                    'duration': duration,
                    'retry_used': used_retry,
                    'cooldown_seconds': PTZ_COOLDOWN_SECONDS,
                }
            except Exception as exc:
                safe_ptz_stop(ptz, profile_token)
                return {'error': f'PTZ move failed: {str(exc)}'}
            finally:
                if move_started:
                    safe_ptz_stop(ptz, profile_token)
                    save_ptz_state(act)
    except TimeoutError as exc:
        return {'error': str(exc)}


def optimize_image(source_path, output_path, max_width=DEFAULT_CAPTURE_MAX_WIDTH, quality=DEFAULT_CAPTURE_QUALITY):
    from PIL import Image, ImageOps

    max_width = max(320, int(max_width))
    quality = max(40, min(int(quality), 95))
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with Image.open(source_path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode != 'RGB':
            image = image.convert('RGB')

        width, height = image.size
        if width > max_width:
            new_height = max(1, int(height * (max_width / width)))
            image = image.resize((max_width, new_height), Image.LANCZOS)

        image.save(output_path, format='JPEG', quality=quality, optimize=True)
        size_bytes = os.path.getsize(output_path)
        return {
            'width': image.width,
            'height': image.height,
            'size_bytes': size_bytes,
        }


def download_snapshot_file(snapshot_uri, user, password, temp_path):
    parsed = urlparse(snapshot_uri)
    if parsed.scheme not in ('http', 'https'):
        raise Exception(f'Unsupported snapshot URI scheme: {parsed.scheme}')

    password_manager = HTTPPasswordMgrWithDefaultRealm()
    password_manager.add_password(None, f'{parsed.scheme}://{parsed.netloc}', user, password)
    opener = build_opener(HTTPBasicAuthHandler(password_manager))
    request = Request(snapshot_uri, headers={'User-Agent': 'AI-Watcher/1.0'})

    with opener.open(request, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as response:
        with open(temp_path, 'wb') as handle:
            shutil.copyfileobj(response, handle)


def capture_via_rtsp(rtsp_uri, temp_path):
    if shutil.which('ffmpeg') is None:
        raise Exception('ffmpeg is required for RTSP frame capture but is not installed or not in PATH')

    command = [
        'ffmpeg',
        '-y',
        '-hide_banner',
        '-loglevel',
        'error',
        '-rtsp_transport',
        'tcp',
        '-i',
        rtsp_uri,
        '-frames:v',
        '1',
        temp_path,
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def cmd_capture(cam, user, password, output_path, prefer='auto', max_width=DEFAULT_CAPTURE_MAX_WIDTH, quality=DEFAULT_CAPTURE_QUALITY):
    attempts = []
    output_path = os.path.abspath(output_path)

    with tempfile.TemporaryDirectory(prefix='ai-watcher-capture-') as temp_dir:
        raw_path = os.path.join(temp_dir, 'raw_frame.jpg')

        if prefer in ('auto', 'snapshot'):
            try:
                snapshot_result = cmd_snapshot_uri(cam)
                if 'SnapshotUri' not in snapshot_result:
                    raise Exception(snapshot_result.get('error', 'Snapshot URI not available'))
                download_snapshot_file(snapshot_result['SnapshotUri'], user, password, raw_path)
                image_info = optimize_image(raw_path, output_path, max_width=max_width, quality=quality)
                return {
                    'status': 'captured',
                    'method': 'snapshot_uri',
                    'output_path': output_path,
                    'max_width': max_width,
                    'quality': quality,
                    **image_info,
                }
            except Exception as exc:
                attempts.append(f'snapshot_uri failed: {exc}')
                if prefer == 'snapshot':
                    return {'error': '; '.join(attempts)}

        if prefer in ('auto', 'rtsp'):
            try:
                stream_result = cmd_stream_uri(cam)
                if 'StreamUri' not in stream_result:
                    raise Exception(stream_result.get('error', 'RTSP stream URI not available'))
                capture_via_rtsp(stream_result['StreamUri'], raw_path)
                image_info = optimize_image(raw_path, output_path, max_width=max_width, quality=quality)
                return {
                    'status': 'captured',
                    'method': 'rtsp',
                    'output_path': output_path,
                    'max_width': max_width,
                    'quality': quality,
                    **image_info,
                }
            except Exception as exc:
                attempts.append(f'rtsp failed: {exc}')
                return {'error': '; '.join(attempts)}

        return {'error': f'Unsupported capture preference: {prefer}'}


def main():
    parser = argparse.ArgumentParser(description='ONVIF Camera Control')
    parser.add_argument('command', choices=['info', 'stream_uri', 'snapshot_uri', 'capture', 'ptz'], help='Command to run')
    parser.add_argument('--act', choices=['up', 'down', 'left', 'right', 'zoomin', 'zoomout', 'home', 'stop'], help='PTZ action')
    parser.add_argument('--duration', type=float, default=0.5, help='PTZ move duration before auto-stop')
    parser.add_argument('--output', default=DEFAULT_CAPTURE_OUTPUT, help='Output path for capture command')
    parser.add_argument('--prefer', choices=['auto', 'snapshot', 'rtsp'], default='auto', help='Capture source preference')
    parser.add_argument('--max-width', type=int, default=DEFAULT_CAPTURE_MAX_WIDTH, help='Max image width for capture output')
    parser.add_argument('--quality', type=int, default=DEFAULT_CAPTURE_QUALITY, help='JPEG quality for capture output (40-95)')

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
        elif parsed.command == 'capture':
            result = cmd_capture(
                cam,
                user=user,
                password=password,
                output_path=parsed.output,
                prefer=parsed.prefer,
                max_width=parsed.max_width,
                quality=parsed.quality,
            )
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
