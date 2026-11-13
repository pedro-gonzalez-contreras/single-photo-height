"""Experimental endpoints for one upright person at a visible wall/floor boundary.

No height labels, camera metadata or per-image coordinates are used. The model
locates the person; pixel geometry selects the crown and supporting floor line.
"""
from pathlib import Path
import cv2
import numpy as np
from download_model import DEFAULT_MODEL, MODEL_SHA256, verify_model
from height_estimation import validate_endpoints


class AutoDetectionError(ValueError):
    """Insufficient evidence: ask for manual annotation instead of guessing."""


def _interval_length(intervals):
    """Union length prevents overlapping Hough segments counting multiple times."""
    total, end = 0., -np.inf
    for start, stop in sorted(intervals):
        total += max(0., stop-max(start, end))
        end = max(end, stop)
    return total


def floor_boundary(image, mask, heel_center, body_height):
    """Find a near-horizontal line supported on BOTH sides of the person."""
    height, width = image.shape[:2]
    hx, hy = heel_center
    radius = max(2, round(body_height*.008))
    foreground = cv2.dilate((mask > .3).astype(np.uint8),
                            np.ones((radius*2+1, radius*2+1), np.uint8))
    edges = cv2.Canny(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY), 40, 120)
    edges[foreground > 0] = 0
    xlo, xhi = max(0, int(hx-.5*body_height)), min(width, int(hx+.5*body_height))
    ylo, yhi = max(0, int(hy-.12*body_height)), min(height, int(hy+.04*body_height))
    search = np.zeros_like(edges)
    search[ylo:yhi, xlo:xhi] = edges[ylo:yhi, xlo:xhi]
    lines = cv2.HoughLinesP(search, 1, np.pi/180, threshold=20,
                            minLineLength=max(15, int(body_height*.06)),
                            maxLineGap=max(3, int(body_height*.015)))
    segments = []
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0].astype(float):
            if x2 < x1:
                x1, y1, x2, y2 = x2, y2, x1, y1
            if x2-x1 < 1 or abs((y2-y1)/(x2-x1)) > .25:
                continue
            if (x2 < hx and hx-x2 < body_height*.22) or (x1 > hx and x1-hx < body_height*.22):
                segments.append((x1, y1, x2, y2))
    candidates = []
    tolerance = max(2., body_height*.006)
    for x1, y1, x2, y2 in segments:
        slope = (y2-y1)/(x2-x1)
        intercept = y1-slope*x1
        inliers = [s for s in segments if max(abs(s[1]-slope*s[0]-intercept),
                                             abs(s[3]-slope*s[2]-intercept)) <= tolerance]
        left = _interval_length([(s[0], s[2]) for s in inliers if s[2] < hx])
        right = _interval_length([(s[0], s[2]) for s in inliers if s[0] > hx])
        if min(left, right) < body_height*.035:
            continue
        # Refit the compatible visible segments, interpolating the occluded gap.
        points = np.array([p for s in inliers for p in [(s[0], s[1]), (s[2], s[3])]])
        weights = np.repeat(np.sqrt([s[2]-s[0] for s in inliers]), 2)
        a = np.column_stack((points[:, 0]-hx, np.ones(len(points))))
        slope, y_at_center = np.linalg.lstsq(a*weights[:, None], points[:, 1]*weights, rcond=None)[0]
        if abs(slope) > .25 or not ylo <= y_at_center < yhi:
            continue
        score = min(left, right)/(1+abs(y_at_center-hy)/(body_height*.045))
        candidates.append({'score': float(score), 'slope': float(slope),
                           'intercept': float(y_at_center-slope*hx),
                           'y_at_center': float(y_at_center),
                           'support_left_px': float(left), 'support_right_px': float(right),
                           'visible_segments': [list(s) for s in inliers]})
    if not candidates:
        raise AutoDetectionError('No floor/wall boundary supported on both sides. Use manual points.')
    candidates.sort(key=lambda c: c['score'], reverse=True)
    best = candidates[0]
    if any(c['score'] > best['score']*.85 and
           abs(c['y_at_center']-best['y_at_center']) > body_height*.02 for c in candidates[1:]):
        raise AutoDetectionError('Several floor lines are plausible. Use manual points.')
    return [float(hx), best['y_at_center']], best


def endpoints_from_pose(image, landmarks, mask):
    """Pure postprocessing, separated from inference for offline tests."""
    h, w = image.shape[:2]
    points, mask = np.asarray(landmarks, dtype=float), np.asarray(mask, dtype=float)
    if mask.shape == (h, w, 1):
        mask = mask[:, :, 0]
    if points.shape != (33, 4) or mask.shape != (h, w) or not np.isfinite(points).all() or not np.isfinite(mask).all():
        raise AutoDetectionError('Invalid pose or segmentation output.')
    required = [0, 11, 12, 23, 24, 25, 26, 27, 28, 29, 30]
    if np.any(points[required, 2:] < .5):
        raise AutoDetectionError('Face, legs or heels are not confidently visible. Use manual points.')
    if np.any(points[required, :2] < [1, 1]) or np.any(points[required, :2] >= [w-1, h-1]):
        raise AutoDetectionError('The person appears cropped. Include head and heels.')
    nose = points[0, :2]
    shoulders = points[11:13, :2]
    heels = points[29:31, :2].mean(axis=0)
    body_height = float(heels[1]-nose[1])
    shoulder_width = float(np.linalg.norm(shoulders[0]-shoulders[1]))
    if body_height < 100 or abs(heels[0]-nose[0]) > .2*body_height or shoulder_width < 10:
        raise AutoDetectionError('Use a larger, upright, nearly level capture.')
    for hip, knee, ankle in [(23, 25, 27), (24, 26, 28)]:
        u, v = points[hip, :2]-points[knee, :2], points[ankle, :2]-points[knee, :2]
        cosine = np.dot(u, v)/max(np.linalg.norm(u)*np.linalg.norm(v), 1e-9)
        if cosine > np.cos(np.deg2rad(150)):
            raise AutoDetectionError('Legs appear bent. Stand upright or use manual points.')
    # Keep the connected foreground component containing the torso.
    _, labels = cv2.connectedComponents((mask > .5).astype(np.uint8))
    torso = points[[11, 12, 23, 24], :2].mean(axis=0).astype(int)
    label = labels[torso[1], torso[0]]
    if label == 0:
        raise AutoDetectionError('Person segmentation does not cover the torso.')
    silhouette = labels == label
    face_to_shoulder = float(shoulders[:, 1].mean()-nose[1])
    if face_to_shoulder <= 0:
        raise AutoDetectionError('Cannot establish the head region.')
    xlo, xhi = max(0, int(nose[0]-.6*shoulder_width)), min(w, int(nose[0]+.6*shoulder_width))
    ylo, yhi = max(0, int(nose[1]-1.4*face_to_shoulder)), min(h, int(nose[1]))
    region = silhouette[ylo:yhi, xlo:xhi]
    rows = np.flatnonzero(region.sum(axis=1) >= max(3, int(shoulder_width*.05)))
    if not len(rows) or rows[0] == 0:
        raise AutoDetectionError('The crown is cropped or ambiguous in the head region.')
    head_y = ylo+int(rows[0])
    head_x = float(np.median(np.flatnonzero(silhouette[head_y, xlo:xhi])+xlo))
    head = [head_x, float(head_y)]
    base, line = floor_boundary(image, mask, heels, body_height)
    endpoints = validate_endpoints([head, base], image.shape)
    return endpoints.tolist(), {
        'algorithm': 'mediapipe_full_v1_crown_and_floor_boundary',
        'person_count': 1, 'head_source': 'Top of connected head silhouette (includes hair).',
        'base_source': 'Visible floor/wall line interpolated at the mean heel x coordinate.',
        'heel_center_pixels': heels.tolist(), 'floor_line': line,
        'min_landmark_visibility': float(points[required, 2].min()),
        'review_recommended': True,
        'limitations': ['Floor identity is a visual heuristic, not semantic proof of the reference plane.',
                        'Hair, headwear, occlusion and shadows can move the endpoints.',
                        'Detection scores are not height uncertainty or calibrated confidence.']}


def detect_endpoints(image, model_path=DEFAULT_MODEL):
    """Run local CPU inference. No automatic network or model downloads."""
    model_path = Path(model_path)
    if not model_path.is_file():
        raise AutoDetectionError('Model missing. Run python download_model.py, or use manual points.')
    verify_model(model_path)
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise AutoDetectionError('Install requirements-auto.txt to enable automatic points.') from exc
    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp.tasks.vision.RunningMode.IMAGE, num_poses=2,
        min_pose_detection_confidence=.5, min_pose_presence_confidence=.5,
        output_segmentation_masks=True)
    try:
        with mp.tasks.vision.PoseLandmarker.create_from_options(options) as detector:
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                                              data=np.ascontiguousarray(image)))
            if len(result.pose_landmarks) != 1:
                raise AutoDetectionError(f'Expected one person; detected {len(result.pose_landmarks)}. Use manual points.')
            if not result.segmentation_masks:
                raise AutoDetectionError('No person segmentation returned.')
            h, w = image.shape[:2]
            points = np.array([[p.x*w, p.y*h, p.visibility, p.presence]
                               for p in result.pose_landmarks[0]])
            mask = result.segmentation_masks[0].numpy_view().copy()
    except RuntimeError as exc:
        raise AutoDetectionError(f'Pose inference failed: {exc}') from exc
    endpoints, details = endpoints_from_pose(image, points, mask)
    details.update(model_sha256=MODEL_SHA256, mediapipe_version=mp.__version__)
    return endpoints, details
