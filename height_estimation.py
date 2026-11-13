"""Metric height from one photo: simple scale or planar homography."""
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass(frozen=True)
class Chessboard:
    columns: int = 9  # Squares, not inner corners.
    rows: int = 6
    square_mm: float = 27.0

    def __post_init__(self):
        if any(not isinstance(v, int) or v < 4 for v in (self.columns, self.rows)):
            raise ValueError('Use at least 4 squares along each board side.')
        if not np.isfinite(self.square_mm) or self.square_mm <= 0:
            raise ValueError('Square size must be finite and positive.')

    @property
    def inner_corners(self):
        return self.columns - 1, self.rows - 1

    def metric_points(self):
        return np.mgrid[0:self.columns-1, 0:self.rows-1].T.reshape(-1, 2).astype(float)*self.square_mm/1000


def load_image(path):
    """Return RGB pixels in the displayed EXIF orientation (also on Windows paths)."""
    with Image.open(Path(path)) as source:
        return np.asarray(ImageOps.exif_transpose(source).convert('RGB')).copy()


def detect_chessboard(image, board):
    image = np.asarray(image)
    if image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
        raise ValueError('Expected a nonempty RGB image.')
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    found, corners = cv2.findChessboardCornersSB(gray, board.inner_corners)
    if not found:
        raise ValueError(
            f'Could not detect the complete {board.columns} x {board.rows} square chessboard '
            f'({board.inner_corners[0]} x {board.inner_corners[1]} inner corners). '
            'Check the layout, focus, resolution and visibility.')
    return corners.reshape(-1, 2).astype(float), board.metric_points()


def validate_endpoints(endpoints, image_shape):
    points = np.asarray(endpoints, dtype=float)
    h, w = image_shape[:2]
    if points.shape != (2, 2) or not np.isfinite(points).all():
        raise ValueError('Supply head and base as two finite (x, y) points.')
    if np.any(points < 0) or np.any(points >= [w, h]):
        raise ValueError('Head and base must lie within the displayed image.')
    if np.linalg.norm(points[1]-points[0]) < 1:
        raise ValueError('Head and base must be different points.')
    return points


def _validate(reference_pixels, reference_meters, endpoints):
    p, w, e = (np.asarray(a, dtype=float) for a in (reference_pixels, reference_meters, endpoints))
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 4 or w.shape != p.shape or e.shape != (2, 2):
        raise ValueError('Expected matching Nx2 board points and 2x2 endpoints.')
    if not all(np.isfinite(a).all() for a in (p, w, e)):
        raise ValueError('Coordinates must be finite.')
    for a in (p, w):
        if len(np.unique(a, axis=0)) != len(a) or np.linalg.matrix_rank(a-a.mean(axis=0)) < 2:
            raise ValueError('Board points must be unique and non-collinear.')
    if np.linalg.norm(e[1]-e[0]) == 0:
        raise ValueError('Endpoints must be distinct.')
    return p, w, e


def estimate_height(reference_pixels, reference_meters, endpoints, method='simple_scale'):
    """Fit only board geometry; known person heights are never an input."""
    p, w, e = _validate(reference_pixels, reference_meters, endpoints)
    if method == 'simple_scale':
        pc, wc = p-p.mean(axis=0), w-w.mean(axis=0)
        u, singular, vt = np.linalg.svd(wc.T @ pc)
        scale = float(singular.sum()/np.sum(wc**2))
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError('Invalid pixel-to-metric scale.')
        fitted = scale*wc @ (u @ vt)+p.mean(axis=0)
        height = float(np.linalg.norm(e[1]-e[0])/scale)
        extra = {'pixels_per_meter': scale}
    elif method == 'homography':
        h, _ = cv2.findHomography(w, p, method=0)
        if h is None or not np.isfinite(h).all() or np.linalg.cond(h) > 1e12:
            raise ValueError('Board homography is degenerate or ill-conditioned.')
        inv = np.linalg.inv(h)
        projected = np.column_stack((e, np.ones(2))) @ inv.T
        if np.any(np.abs(projected[:, 2]) < 1e-12):
            raise ValueError('An endpoint projects to infinity.')
        metric = projected[:, :2]/projected[:, 2, None]
        height = float(np.linalg.norm(metric[1]-metric[0]))
        fitted = cv2.perspectiveTransform(w.reshape(-1, 1, 2), h).reshape(-1, 2)
        extra = {'endpoints_m': metric.tolist()}
    else:
        raise ValueError('Method must be simple_scale or homography.')
    if not np.isfinite(height) or height <= 0:
        raise ValueError('Invalid height estimate.')
    return {'method': method, 'height_m': height, 'height_cm': height*100,
            'reference_rms_px': float(np.sqrt(np.mean(np.sum((fitted-p)**2, axis=1)))),
            'reference_points': len(p), **extra}


def measure(corners, metric_points, endpoints, board, image_shape, method='both'):
    endpoints = validate_endpoints(endpoints, image_shape)
    methods = ['simple_scale', 'homography'] if method == 'both' else [method]
    results = {}
    for name in methods:
        try:
            results[name] = {'status': 'ok', **estimate_height(corners, metric_points, endpoints, name)}
        except (ValueError, np.linalg.LinAlgError, cv2.error) as exc:
            results[name] = {'status': 'failed', 'reason': str(exc)}
    if all(r['status'] == 'failed' for r in results.values()):
        raise ValueError('; '.join(r['reason'] for r in results.values()))
    return {'board': {'squares': [board.columns, board.rows], 'inner_corners': list(board.inner_corners),
                      'square_mm': board.square_mm},
            'image_size': [image_shape[1], image_shape[0]],
            'endpoints_pixels': endpoints.tolist(), 'measurements': results,
            'assumptions': ['Reference and measured endpoints share one plane.',
                            'Simple scale requires an approximately frontal capture.',
                            'Lens distortion is assumed negligible; no intrinsic calibration is estimated.'],
            'endpoint_source': 'Manual head and floor/heel-base points in EXIF-oriented full image.',
            'limitation': 'Board fit RMS is not a person-height accuracy estimate.'}
