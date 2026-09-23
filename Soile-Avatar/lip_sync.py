"""Optional one-time CPU phonetic analysis, separate from rendering and providers."""
import base64
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from config import RHUBARB_PATH, FFMPEG_PATH

MAX_AUDIO_BYTES = 20 * 1024 * 1024


def validate_cues(payload):
    cues = payload.get('mouthCues') if isinstance(payload, dict) else payload
    if not isinstance(cues, list) or len(cues) > 100000:
        raise ValueError('Нужен массив mouthCues (не более 100000 элементов).')
    result, previous = [], 0.0
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError('Некорректный элемент mouthCues.')
        start, end, value = cue.get('start'), cue.get('end'), cue.get('value')
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or start < previous or end <= start or end > 3600
                or value not in tuple('ABCDEFGHX')):
            raise ValueError('Visemes: нужны непересекающиеся интервалы в секундах и значения A–H/X.')
        result.append(dict(start=start, end=end, value=value))
        previous = end
    return result


def prepare_audio(data: bytes, suffix: str, cue_json: bytes | None = None) -> dict:
    suffix = suffix.lower()
    if suffix not in ('.wav', '.mp3') or not data or len(data) > MAX_AUDIO_BYTES:
        raise ValueError('Загрузите WAV/MP3 размером до 20 МБ.')
    cues, mode = [], 'amplitude'
    if cue_json is not None:
        if len(cue_json) > 5 * 1024 * 1024:
            raise ValueError('JSON должен быть не больше 5 МБ.')
        cues, mode = validate_cues(json.loads(cue_json)), 'visemes'
    elif shutil.which(RHUBARB_PATH):
        with TemporaryDirectory(prefix='soile-lipsync-') as directory:
            source = Path(directory) / ('voice' + suffix)
            source.write_bytes(data)
            if suffix == '.mp3':
                if not shutil.which(FFMPEG_PATH):
                    raise ValueError('Для анализа MP3 нужен FFmpeg; используйте WAV или готовый JSON.')
                wav = Path(directory) / 'voice.wav'
                subprocess.run([FFMPEG_PATH, '-nostdin', '-v', 'error', '-i', str(source),
                                '-ac', '1', '-ar', '16000', str(wav)],
                               check=True, capture_output=True, timeout=60)
                source = wav
            output = subprocess.run([RHUBARB_PATH, '-r', 'phonetic', '-f', 'json', str(source)],
                                    check=True, capture_output=True, timeout=120)
            cues, mode = validate_cues(json.loads(output.stdout)), 'visemes'
    mime = 'audio/wav' if suffix == '.wav' else 'audio/mpeg'
    return dict(id=hashlib.sha256(data + (cue_json or b'') + mode.encode()).hexdigest(),
                src=f'data:{mime};base64,' + base64.b64encode(data).decode('ascii'),
                cues=cues, mode=mode)
