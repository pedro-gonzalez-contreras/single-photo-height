"""Generate original geometric illustrations; no real people or private images."""
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def generate(output=Path('examples')):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (1800, 2400), '#e8edf3')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    draw.text((100, 60), 'SYNTHETIC SCENE | not a real-person accuracy test', fill='#29394f', font=font)
    # A vertical 1800 px segment at 1000 px/m is exactly 1.80 m.
    head, base = [1100., 230.], [1100., 2030.]
    draw.rectangle((80, 2030, 1720, 2036), fill='#8999ac')
    draw.ellipse((1000, 230, 1200, 430), fill='#3864a0')
    draw.rounded_rectangle((945, 435, 1255, 1250), radius=75, fill='#3864a0')
    draw.line((985, 500, 885, 1120), fill='#3864a0', width=70)
    draw.line((1215, 500, 1315, 1120), fill='#3864a0', width=70)
    draw.rectangle((970, 1200, 1080, 2029), fill='#3864a0')
    draw.rectangle((1120, 1200, 1230, 2029), fill='#3864a0')
    draw.text((100, 2180), 'Click crown, then floor base between the heels.', fill='#29394f', font=font)
    # Board is drawn last to preserve exact square edges. 27 px = 27 mm.
    x0, y0, square = 300, 700, 27
    draw.rectangle((x0-35, y0-35, x0+9*square+35, y0+6*square+35), fill='white')
    for y in range(6):
        for x in range(9):
            if (x+y)%2 == 0:
                draw.rectangle((x0+x*square, y0+y*square, x0+(x+1)*square-1, y0+(y+1)*square-1), fill='black')
    array = np.asarray(image)
    transforms = {
        'frontal': np.eye(3),
        'perspective': np.array([[.88, .045, 60.], [-.025, .94, 70.], [.00005, -.00004, 1.]])}
    examples = []
    for name, h in transforms.items():
        warped = cv2.warpPerspective(array, h, image.size, flags=cv2.INTER_LINEAR, borderValue=(232, 237, 243))
        Image.fromarray(warped).save(output/f'{name}.png')
        ends = cv2.perspectiveTransform(np.array([head, base]).reshape(-1, 1, 2), h).reshape(-1, 2)
        examples.append({'image': f'{name}.png', 'head': ends[0].tolist(), 'base': ends[1].tolist(),
                         'ground_truth_height_m': 1.8, 'squares': [9, 6], 'square_mm': 27,
                         'generation_homography': h.tolist()})
    (output/'annotations.json').write_text(json.dumps({'source': 'Generated entirely by generate_examples.py',
        'warning': 'Ideal coplanar synthetic illustrations, not validation on real people.', 'examples': examples}, indent=2)+'\n', encoding='utf-8')
    return examples


if __name__ == '__main__':
    generate()
    print('Created examples/frontal.png, examples/perspective.png and annotations.json')
