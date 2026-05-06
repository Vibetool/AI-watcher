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
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import (
    HTTPBasicAuthHandler,
    HTTPDigestAuthHandler,
    HTTPPasswordMgrWithDefaultRealm,
    Request,
    build_opener,
)

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
DEFAULT_ONVIF_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_ONVIF_OPERATION_TIMEOUT_SECONDS = 15

# Stable error codes — Agents branch on these instead of parsing free-form
# error strings. Add new codes when a new failure mode is introduced; never
# rename an existing code.
ERROR_AUTH_FAILED = 'AUTH_FAILED'
ERROR_UNREACHABLE = 'UNREACHABLE'
ERROR_TIMEOUT = 'TIMEOUT'
ERROR_NOT_ONVIF = 'NOT_ONVIF'
ERROR_NO_PTZ = 'NO_PTZ'
ERROR_NO_MEDIA_PROFILE = 'NO_MEDIA_PROFILE'
ERROR_PTZ_BUSY = 'PTZ_BUSY'
ERROR_PTZ_INVALID_DURATION = 'PTZ_INVALID_DURATION'
ERROR_CAPTURE_FAILED = 'CAPTURE_FAILED'
ERROR_INVALID_CONFIG = 'INVALID_CONFIG'
ERROR_INVALID_ARGS = 'INVALID_ARGS'
ERROR_UNSUPPORTED = 'UNSUPPORTED'
ERROR_DEPENDENCY_MISSING = 'DEPENDENCY_MISSING'
ERROR_UNKNOWN = 'UNKNOWN'


def classify_error(exc):
    """Map an exception (or string) to a stable error code.

    Pattern-matches on both the exception class name and its string form so
    the same classifier works whether we got a zeep/urllib/onvif exception
    or a plain re-raised message.
    """
    text = str(exc).lower()
    name = type(exc).__name__ if isinstance(exc, BaseException) else ''

    if name in ('TimeoutError', 'ConnectTimeoutError', 'ReadTimeoutError'):
        return ERROR_TIMEOUT
    if 'timeout' in text or 'timed out' in text:
        return ERROR_TIMEOUT
    if any(s in text for s in ('401', 'unauthorized', 'authentication failed', 'authenticationfailed', 'not authorized', 'sender not authorized')):
        return ERROR_AUTH_FAILED
    if any(s in text for s in (
        'no route to host', 'network is unreachable', 'connection refused',
        'host is down', 'name or service not known', 'nodename nor servname',
        'failed to establish a new connection', 'max retries exceeded',
    )):
        return ERROR_UNREACHABLE
    if any(s in text for s in ('xmlsyntaxerror', 'not well-formed', 'expected element', 'no element found')):
        return ERROR_NOT_ONVIF
    return ERROR_UNKNOWN


def err(message, code=None, source_exc=None):
    """Build a structured error response: {'error': <human msg>, 'error_code': <stable code>}."""
    if code is None:
        code = classify_error(source_exc) if source_exc is not None else ERROR_UNKNOWN
    return {'error': str(message), 'error_code': code}


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
        return err(exc, source_exc=exc)


class NoMediaProfileError(Exception):
    """Raised when the camera reports no media profiles — usually means the
    device speaks ONVIF for device-management but not for media (rare) or is
    misconfigured. Mapped to ERROR_NO_MEDIA_PROFILE upstream."""


def get_media_profile(cam):
    media = cam.create_media_service()
    profiles = media.GetProfiles()
    if not profiles:
        raise NoMediaProfileError('No media profiles found on device')
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
    except Exception as exc:
        return err('Camera does not support PTZ or PTZ service could not be initialized', code=ERROR_NO_PTZ, source_exc=exc)

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
                    return err(f'GotoHomePosition failed: {str(exc)}', source_exc=exc)

            if duration <= 0:
                return err(
                    'For safety, PTZ move duration must be greater than 0 so the camera can auto-stop.',
                    code=ERROR_PTZ_INVALID_DURATION,
                )

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
                return err(f'PTZ move failed: {str(exc)}', source_exc=exc)
            finally:
                if move_started:
                    safe_ptz_stop(ptz, profile_token)
                    save_ptz_state(act)
    except TimeoutError as exc:
        return err(exc, code=ERROR_PTZ_BUSY)


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


class UnsupportedSnapshotSchemeError(Exception):
    """Raised when the snapshot URI uses a scheme we don't handle (e.g. rtsp://).
    Mapped to ERROR_UNSUPPORTED upstream."""


def download_snapshot_file(snapshot_uri, user, password, temp_path):
    parsed = urlparse(snapshot_uri)
    if parsed.scheme not in ('http', 'https'):
        raise UnsupportedSnapshotSchemeError(f'Unsupported snapshot URI scheme: {parsed.scheme}')

    password_manager = HTTPPasswordMgrWithDefaultRealm()
    password_manager.add_password(None, f'{parsed.scheme}://{parsed.netloc}', user, password)
    # Many ONVIF cameras (Hikvision/Dahua/Reolink/Axis) use Digest auth on the
    # snapshot endpoint; register both Basic and Digest handlers so the opener
    # can satisfy whichever WWW-Authenticate scheme the camera challenges with.
    opener = build_opener(
        HTTPBasicAuthHandler(password_manager),
        HTTPDigestAuthHandler(password_manager),
    )
    request = Request(snapshot_uri, headers={'User-Agent': 'AI-Watcher/1.0'})

    with opener.open(request, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as response:
        with open(temp_path, 'wb') as handle:
            shutil.copyfileobj(response, handle)


class FFmpegMissingError(Exception):
    """Raised when ffmpeg is not on PATH.
    Mapped to ERROR_DEPENDENCY_MISSING upstream."""


def inject_rtsp_credentials(rtsp_uri, user, password):
    """Return an RTSP URL with `user:password@` injected into the netloc.

    ONVIF GetStreamUri typically returns a credential-less URL (e.g.
    `rtsp://192.168.1.60:554/stream1`), but many cameras (TP-Link,
    Reolink, some Dahua firmwares) require RTSP-level Basic/Digest auth
    and ffmpeg has no reliable cross-version flag for that — embedding
    creds in the URL is the portable answer.

    Behavior:
    - If `rtsp_uri` already contains a username, return it unchanged
      (some cameras pre-embed creds in the ONVIF response).
    - If `user` or `password` is falsy, return `rtsp_uri` unchanged.
    - Credentials are percent-encoded so `@`, `:`, `/`, `%`, etc. in
      passwords don't break the URL.
    - IPv6 hostnames are wrapped in brackets per RFC 3986.
    """
    if not user or not password:
        return rtsp_uri

    parsed = urlparse(rtsp_uri)
    if parsed.username:
        return rtsp_uri

    host = parsed.hostname or ''
    if ':' in host:  # IPv6 literal — bracket per RFC 3986
        host = f'[{host}]'

    user_q = quote(str(user), safe='')
    password_q = quote(str(password), safe='')

    netloc = f'{user_q}:{password_q}@{host}'
    if parsed.port:
        netloc = f'{netloc}:{parsed.port}'

    return urlunparse(parsed._replace(netloc=netloc))


def capture_via_rtsp(rtsp_uri, temp_path):
    if shutil.which('ffmpeg') is None:
        raise FFmpegMissingError('ffmpeg is required for RTSP frame capture but is not installed or not in PATH')

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


def _pick_capture_error_code(exceptions):
    """Among the exceptions hit during capture, prefer the most actionable
    code so the Agent can give the user the right next step.

    Priority: AUTH_FAILED > UNREACHABLE > TIMEOUT > NOT_ONVIF > DEPENDENCY_MISSING > UNSUPPORTED > CAPTURE_FAILED.
    """
    seen = []
    for exc in exceptions:
        if isinstance(exc, FFmpegMissingError):
            seen.append(ERROR_DEPENDENCY_MISSING)
        elif isinstance(exc, UnsupportedSnapshotSchemeError):
            seen.append(ERROR_UNSUPPORTED)
        else:
            seen.append(classify_error(exc))
    priority = [
        ERROR_AUTH_FAILED, ERROR_UNREACHABLE, ERROR_TIMEOUT, ERROR_NOT_ONVIF,
        ERROR_DEPENDENCY_MISSING, ERROR_UNSUPPORTED,
    ]
    for code in priority:
        if code in seen:
            return code
    return ERROR_CAPTURE_FAILED


def cmd_capture(cam, user, password, output_path, prefer='auto', max_width=DEFAULT_CAPTURE_MAX_WIDTH, quality=DEFAULT_CAPTURE_QUALITY):
    attempts = []
    raised = []
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
                raised.append(exc)
                if prefer == 'snapshot':
                    return err('; '.join(attempts), code=_pick_capture_error_code(raised))

        if prefer in ('auto', 'rtsp'):
            try:
                stream_result = cmd_stream_uri(cam)
                if 'StreamUri' not in stream_result:
                    raise Exception(stream_result.get('error', 'RTSP stream URI not available'))
                # ONVIF stream URIs are typically credential-less; inject
                # auth so cameras that require RTSP Basic/Digest (TP-Link,
                # Reolink, etc.) don't 401 ffmpeg.
                rtsp_uri = inject_rtsp_credentials(stream_result['StreamUri'], user, password)
                capture_via_rtsp(rtsp_uri, raw_path)
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
                raised.append(exc)
                return err('; '.join(attempts), code=_pick_capture_error_code(raised))

        return err(f'Unsupported capture preference: {prefer}', code=ERROR_UNSUPPORTED)


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
        print(json.dumps({'ok': False, **err('Invalid port value in scripts/config.ini', code=ERROR_INVALID_CONFIG)}))
        sys.exit(1)

    if not ip or not user or not password:
        print(json.dumps({'ok': False, **err(
            'Missing camera configuration. Run the setup wizard first or provide --ip, --user, and --password.',
            code=ERROR_INVALID_CONFIG,
        )}))
        sys.exit(1)

    # Fail fast on missing PTZ action before opening a SOAP connection — the
    # ONVIFCamera constructor performs network I/O (GetCapabilities), so an
    # invalid invocation should not pay that latency.
    if parsed.command == 'ptz' and not parsed.act:
        print(json.dumps({'ok': False, **err('Missing --act argument for PTZ command', code=ERROR_INVALID_ARGS)}))
        sys.exit(1)

    try:
        import onvif
        from zeep.transports import Transport

        wsdl_dir = os.path.join(os.path.dirname(os.path.dirname(onvif.__file__)), 'wsdl')
        # Bound network calls so an unreachable camera fails fast (default zeep
        # transport has timeout=300 and operation_timeout=None which means we'd
        # otherwise hang on the OS-level TCP timeout, ~75s on Linux/macOS).
        transport = Transport(
            timeout=DEFAULT_ONVIF_CONNECT_TIMEOUT_SECONDS,
            operation_timeout=DEFAULT_ONVIF_OPERATION_TIMEOUT_SECONDS,
        )
        cam = onvif.ONVIFCamera(ip, port, user, password, wsdl_dir, transport=transport)

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
            # parsed.act is guaranteed non-empty: validated before ONVIFCamera()
            result = cmd_ptz(cam, parsed.act, parsed.duration)
        else:
            result = err('Command not yet implemented', code=ERROR_UNSUPPORTED)

        print(json.dumps({'ok': 'error' not in result, 'result': result}, indent=2))

    except NoMediaProfileError as exc:
        print(json.dumps({'ok': False, **err(exc, code=ERROR_NO_MEDIA_PROFILE)}))
        sys.exit(1)
    except Exception as exc:
        # Outer net: connection refused / DNS / 401 / SOAP fault / etc.
        # classify_error() handles the common cases; everything else falls to UNKNOWN.
        print(json.dumps({'ok': False, **err(exc, source_exc=exc)}))
        sys.exit(1)


if __name__ == '__main__':
    main()
