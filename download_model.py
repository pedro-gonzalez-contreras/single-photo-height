"""Explicit one-time download; measurement itself never downloads a model."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

MODEL_URL = ('https://storage.googleapis.com/mediapipe-models/pose_landmarker/'
             'pose_landmarker_full/float16/1/pose_landmarker_full.task')
MODEL_SHA256 = '5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1'
DEFAULT_MODEL = Path(__file__).resolve().parent/'models'/'pose_landmarker_full.task'


def verify_model(path):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError('Model checksum differs from the supported MediaPipe full v1 bundle.')


def download(path):
    path = Path(path)
    if path.exists():
        verify_model(path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.download')
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            data = response.read(20_000_001)
        if len(data) > 20_000_000:
            raise ValueError('Unexpectedly large model download.')
        temporary.write_bytes(data)
        verify_model(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    try:
        print(f'Model ready: {download(args.output)}')
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Model setup failed: {exc}\n')
