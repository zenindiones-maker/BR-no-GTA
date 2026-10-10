"""YouTube playback and acoustic evidence are distinct capabilities."""
import re
from urllib.parse import urlparse, parse_qs

PATTERN = re.compile(r"[A-Za-z0-9_-]{11}\Z")

def parse_youtube_video_id(value):
    if not isinstance(value, str):
        raise ValueError('invalid reference')
    if PATTERN.fullmatch(value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.hostname not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'):
        raise ValueError('not an official YouTube URL')
    if parsed.hostname == 'youtu.be':
        candidate = parsed.path.strip('/')
    elif parsed.path == '/watch':
        ids = parse_qs(parsed.query).get('v', [])
        candidate = ids[0] if len(ids) == 1 else ''
    else:
        candidate = ''
    if not PATTERN.fullmatch(candidate):
        raise ValueError('invalid video id')
    return candidate

def build_perception_manifest(value):
    video_id = parse_youtube_video_id(value)
    return {'schema': 'HarnessYouTubeMediaPerception/v1', 'video_id': video_id, 'playback': {'method': 'youtube-iframe', 'embed_url': 'https://www.youtube.com/embed/' + video_id + '?enablejsapi=1'}, 'audio_perception': {'status': 'NOT_OBSERVED', 'lexicon_activation': False, 'requires_authorized_media': True}}

def classify_acquisition_error(message):
    msg = message.lower()
    if 'po token' in msg: return 'PLAYBACK_TOKEN_REQUIRED'
    if 'name resolution' in msg or 'dns' in msg: return 'NETWORK_DNS'
    if '403' in msg or 'forbidden' in msg: return 'ACCESS_DENIED'
    return 'UNKNOWN'
