import importlib.util
from pathlib import Path
import subprocess
import sys
import cv2
import numpy as np
import pytest
from auto_endpoints import AutoDetectionError, detect_endpoints, endpoints_from_pose, floor_boundary
from download_model import DEFAULT_MODEL, verify_model

ROOT = Path(__file__).resolve().parents[1]


def scene():
    """Controlled wall, silhouette and model outputs; no private photos."""
    image = np.full((600, 800, 3), 220, np.uint8)
    image[500:] = 100
    mask = np.zeros((600, 800), np.float32)
    cv2.ellipse(mask, (400, 120), (30, 40), 0, 0, 360, 1., -1)
    cv2.rectangle(mask, (355, 140), (445, 510), 1., -1)
    image[mask > .5] = [30, 40, 60]
    landmarks = np.tile([400., 300., 1., 1.], (33, 1))
    landmarks[0, :2] = [400, 125]
    landmarks[11:13, :2] = [[355, 190], [445, 190]]
    landmarks[23:25, :2] = [[380, 320], [420, 320]]
    landmarks[25:27, :2] = [[380, 410], [420, 410]]
    landmarks[27:29, :2] = [[380, 490], [420, 490]]
    landmarks[29:31, :2] = [[380, 510], [420, 510]]
    return image, landmarks, mask


def test_auto_uses_crown_and_wall_line_not_lowest_toe_or_raw_heel():
    image, landmarks, mask = scene()
    # A disconnected foreground artifact must not become the head.
    mask[60:64, 395:405] = 1
    points, details = endpoints_from_pose(image, landmarks, mask[..., None])
    assert points[0][1] == pytest.approx(80, abs=2)
    assert points[1] == pytest.approx([400, 500], abs=2)
    assert points[1][1] < details['heel_center_pixels'][1]-5
    assert details['review_recommended']


@pytest.mark.parametrize('issue', ['hidden_heel', 'cropped', 'bent_knee', 'missing_torso', 'nonfinite'])
def test_unreliable_pose_does_not_produce_height(issue):
    image, landmarks, mask = scene()
    if issue == 'hidden_heel': landmarks[29, 2] = .1
    elif issue == 'cropped': landmarks[30, 1] = 650
    elif issue == 'bent_knee': landmarks[25, :2] = [460, 320]
    elif issue == 'missing_torso': mask[:] = 0
    else: mask[1, 1] = np.nan
    with pytest.raises(AutoDetectionError):
        endpoints_from_pose(image, landmarks, mask)


def test_one_sided_edge_is_not_enough_for_floor_interpolation():
    image, landmarks, mask = scene()
    image[500:, 450:] = 220  # Remove support to the right of the person.
    with pytest.raises(AutoDetectionError, match='both sides'):
        floor_boundary(image, mask, landmarks[29:31, :2].mean(axis=0), 385)


def test_no_edge_is_not_mistaken_for_floor():
    image, landmarks, mask = scene()
    image[:] = 220
    with pytest.raises(AutoDetectionError):
        floor_boundary(image, mask, landmarks[29:31, :2].mean(axis=0), 385)


def test_model_missing_fails_without_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Measurement must not download anything')
    monkeypatch.setattr('urllib.request.urlopen', forbidden)
    with pytest.raises(AutoDetectionError, match='Model missing'):
        detect_endpoints(np.zeros((100, 100, 3), np.uint8), tmp_path/'missing.task')


def test_corrupt_model_is_rejected(tmp_path):
    path = tmp_path/'corrupt.task'
    path.write_bytes(b'not a model')
    with pytest.raises(ValueError, match='checksum'):
        verify_model(path)


def test_cli_auto_and_manual_flags_cannot_be_mixed():
    run = subprocess.run([sys.executable, str(ROOT/'measure.py'), 'unused.jpg',
                          '--auto', '--head', '1', '2'], capture_output=True, text=True)
    assert run.returncode == 2
    assert 'either --auto' in run.stderr


def test_cli_missing_auto_model_creates_no_measurement(tmp_path):
    output = tmp_path/'result.json'
    run = subprocess.run([sys.executable, str(ROOT/'measure.py'), str(ROOT/'examples/frontal.png'),
                          '--auto', '--model', str(tmp_path/'missing.task'), '--output', str(output)],
                         capture_output=True, text=True)
    assert run.returncode == 2
    assert 'Model missing' in run.stderr
    assert not output.exists()


@pytest.mark.skipif(not DEFAULT_MODEL.is_file() or importlib.util.find_spec('mediapipe') is None,
                    reason='Optional local MediaPipe/model integration test; no downloads in tests.')
def test_real_model_rejects_blank_image():
    with pytest.raises(AutoDetectionError, match='detected 0'):
        detect_endpoints(np.full((480, 640, 3), 220, np.uint8))
