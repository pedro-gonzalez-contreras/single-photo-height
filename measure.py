"""Headless CLI: detect the board and use automatic or explicit image points."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from height_estimation import Chessboard, load_image, detect_chessboard, measure
from download_model import DEFAULT_MODEL


def save_result(image, result, output):
    output = Path(output)
    overlay = output.with_name(output.stem+'_annotated.png')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Re-encode RGB pixels without EXIF; source photos are never changed.
    canvas = Image.fromarray(image).convert('RGB')
    draw = ImageDraw.Draw(canvas)
    if 'automatic_endpoints' in result:
        line = result['automatic_endpoints']['floor_line']
        segments = line['visible_segments']
        left, right = min(s[0] for s in segments), max(s[2] for s in segments)
        draw.line((left, line['slope']*left+line['intercept'],
                   right, line['slope']*right+line['intercept']), fill='#00cfff', width=2)
    radius = max(5, round(min(image.shape[:2])*.008))
    for point, color in zip(result['endpoints_pixels'], ['#00ff7f', '#ff4545']):
        x, y = point
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), outline='black', width=5)
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), outline=color, width=2)
        draw.line((x-radius*2, y, x+radius*2, y), fill=color, width=2)
        draw.line((x, y-radius*2, x, y+radius*2), fill=color, width=2)
    font = ImageFont.load_default(size=max(14, min(40, image.shape[1]//45)))
    text = ' | '.join(f"{name}: {r['height_cm']:.1f} cm" if r['status']=='ok' else f'{name}: failed'
                      for name, r in result['measurements'].items())
    box = draw.textbbox((12, 12), text, font=font)
    draw.rectangle((0, 0, min(image.shape[1], box[2]+12), box[3]+12), fill='white')
    draw.text((12, 12), text, fill='black', font=font)
    canvas.save(overlay)
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--squares', type=int, nargs=2, default=[9, 6], metavar=('COLS', 'ROWS'))
    parser.add_argument('--square-mm', type=float, default=27.)
    parser.add_argument('--head', type=float, nargs=2, metavar=('X', 'Y'))
    parser.add_argument('--base', type=float, nargs=2, metavar=('X', 'Y'))
    parser.add_argument('--auto', action='store_true', help='Detect crown and floor/wall base without clicks.')
    parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    parser.add_argument('--method', choices=['simple_scale', 'homography', 'both'], default='both')
    parser.add_argument('--output', type=Path, default=Path('outputs/measurement.json'))
    args = parser.parse_args()
    if args.auto and (args.head is not None or args.base is not None):
        parser.error('Use either --auto or both --head and --base.')
    if not args.auto and (args.head is None or args.base is None):
        parser.error('Supply --auto, or both --head and --base.')
    try:
        if args.output.resolve() == args.image.resolve() or args.output.with_name(args.output.stem+'_annotated.png').resolve() == args.image.resolve():
            raise ValueError('Choose output paths different from the input photo.')
        image = load_image(args.image)
        board = Chessboard(*args.squares, args.square_mm)
        corners, world = detect_chessboard(image, board)
        endpoints, details = [args.head, args.base], None
        if args.auto:
            from auto_endpoints import detect_endpoints
            endpoints, details = detect_endpoints(image, args.model)
        result = measure(corners, world, endpoints, board, image.shape, args.method)
        if details is not None:
            result['endpoint_source'] = 'Automatic crown segmentation and floor/wall boundary; unreviewed.'
            result['automatic_endpoints'] = details
        overlay = save_result(image, result, args.output)
        for name, value in result['measurements'].items():
            print(f"{name}: {value['height_cm']:.2f} cm" if value['status']=='ok' else f"{name}: FAILED ({value['reason']})")
        print(f'Results: {args.output}\nAnnotated image: {overlay}')
        if details is not None:
            print('Automatic points are experimental. Review the annotated image; floor identity is heuristic.')
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Measurement failed: {exc}\n')


if __name__ == '__main__':
    main()
