import json
import subprocess
import sys
from pathlib import Path
import cv2
import numpy as np
import pytest
from height_estimation import Chessboard, detect_chessboard, estimate_height, load_image, measure, validate_endpoints
from generate_examples import generate

ROOT = Path(__file__).resolve().parents[1]


def projected_scene():
    world = Chessboard().metric_points()
    ends = np.array([[.5, -.2], [.5, 1.6]], dtype=float)
    h = np.array([[420., 20., 350.], [10., 400., 150.], [.09, -.07, 1.]])
    project = lambda a: cv2.perspectiveTransform(a.reshape(-1, 1, 2), h).reshape(-1, 2)
    return world, project(world), project(ends)


def test_homography_recovers_known_length_and_metric_scale():
    world, pixels, endpoints = projected_scene()
    assert estimate_height(pixels, world, endpoints, 'homography')['height_m'] == pytest.approx(1.8, abs=1e-5)
    assert estimate_height(pixels, world*2, endpoints, 'homography')['height_m'] == pytest.approx(3.6, abs=2e-5)


def test_simple_scale_recovers_rotated_frontal_scene():
    world = Chessboard().metric_points()
    r = np.array([[.8, -.6], [.6, .8]])
    pixels = world @ r.T*500+[300, 100]
    endpoints = np.array([[.5, 0], [.5, 1.81]]) @ r.T*500+[300, 100]
    assert estimate_height(pixels, world, endpoints)['height_m'] == pytest.approx(1.81)


def test_simple_scale_does_not_claim_perspective_correction():
    w, p, e = projected_scene()
    assert abs(estimate_height(p, w, e)['height_m']-1.8) > .02


@pytest.mark.parametrize('method', ['simple_scale', 'homography'])
@pytest.mark.parametrize('bad', ['duplicate', 'collinear', 'nan'])
def test_invalid_board_rejected(method, bad):
    w, p, e = projected_scene()
    if bad == 'duplicate': p[1] = p[0]
    elif bad == 'collinear': p[:, 1] = p[:, 0]
    else: p[0, 0] = np.nan
    with pytest.raises(ValueError):
        estimate_height(p, w, e, method)


@pytest.mark.parametrize('points', [[[1, 1], [1, 1]], [[-1, 5], [20, 50]], [[0, 0], [100, 20]], [[0, 0], [20, float('inf')]]])
def test_invalid_endpoints_rejected(points):
    with pytest.raises(ValueError): validate_endpoints(points, (100, 100, 3))


def test_wrong_layout_and_blank_image_fail_clearly():
    with pytest.raises(ValueError): Chessboard(square_mm=0)
    with pytest.raises(ValueError, match='Could not detect'):
        detect_chessboard(np.full((400, 500, 3), 255, np.uint8), Chessboard())


def test_synthetic_examples_detect_and_measure_without_private_data(tmp_path):
    examples = generate(tmp_path)
    for entry in examples:
        image = load_image(tmp_path/entry['image'])
        p, w = detect_chessboard(image, Chessboard())
        assert len(p) == 40
        result = measure(p, w, [entry['head'], entry['base']], Chessboard(), image.shape)
        assert result['measurements']['homography']['height_m'] == pytest.approx(1.8, abs=.025)
        if entry['image'] == 'frontal.png':
            assert result['measurements']['simple_scale']['height_m'] == pytest.approx(1.8, abs=.003)


def test_cli_generates_json_and_overlay(tmp_path):
    entry = generate(tmp_path)[0]
    output = tmp_path/'results'/'height.json'
    run = subprocess.run([sys.executable, str(ROOT/'measure.py'), str(tmp_path/entry['image']),
        '--head', *map(str, entry['head']), '--base', *map(str, entry['base']), '--output', str(output)],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    result = json.loads(output.read_text())
    assert result['measurements']['simple_scale']['height_cm'] == pytest.approx(180, abs=.3)
    assert output.with_name('height_annotated.png').is_file()


def test_cli_cannot_overwrite_source_photo(tmp_path):
    entry = generate(tmp_path)[0]
    source = tmp_path/entry['image']
    original = source.read_bytes()
    run = subprocess.run([sys.executable, str(ROOT/'measure.py'), str(source), '--head', '1100', '230',
                          '--base', '1100', '2030', '--output', str(source)], capture_output=True, text=True)
    assert run.returncode == 2
    assert source.read_bytes() == original


def test_exif_rotation_uses_displayed_image_frame(tmp_path):
    from PIL import Image
    image = Image.new('RGB', (80, 40), 'white')
    exif = Image.Exif(); exif[274] = 6
    path = tmp_path/'rotated.jpg'; image.save(path, exif=exif)
    assert load_image(path).shape == (80, 40, 3)
