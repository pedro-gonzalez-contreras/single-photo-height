from concurrent.futures import Future
from pathlib import Path
import pytest

tk = pytest.importorskip('tkinter', reason='Optional GUI tests require Tkinter.')

from demo import HeightDemo
from height_estimation import Chessboard

EXAMPLE = Path(__file__).resolve().parents[1]/'examples'/'frontal.png'


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Tk/display unavailable for GUI integration tests.')
    root.withdraw()
    instance = HeightDemo(root, Chessboard(), automatic=False)
    try:
        yield instance
    finally:
        instance.close()


def test_square_size_recalculates_preserving_points_and_validates_input(app, monkeypatch):
    app.load(EXAMPLE)
    app.points = [[1100, 230], [1100, 2030]]
    app.update_measurement()
    original = app.result['measurements']['simple_scale']['height_cm']
    previous_token = app.generation
    app.square_text.set('54')
    assert str(app.save['state']) == 'disabled'
    app.apply_board()
    assert app.points == [[1100, 230], [1100, 2030]]
    assert app.result['board']['square_mm'] == 54
    assert app.result['measurements']['simple_scale']['height_cm'] == pytest.approx(2*original)
    # An inference started before changing the reference must not overwrite it.
    stale = Future()
    stale.set_exception(AssertionError('Stale result was inspected'))
    app.finish_auto(stale, previous_token)
    assert app.result['board']['square_mm'] == 54
    app.square_text.set('27,5')
    app.apply_board()
    assert app.result['board']['square_mm'] == 27.5
    messages = []
    monkeypatch.setattr('demo.messagebox.showerror', lambda *args: messages.append(args))
    app.square_text.set('nan')
    app.apply_board()
    assert messages
    assert app.board.square_mm == 27.5
    assert str(app.save['state']) == 'disabled'


def test_wrong_pattern_can_be_fixed_without_reopening_photo(app):
    app.pattern_text.set('10 x 7')
    app.load(EXAMPLE)
    assert app.image is not None and app.path == EXAMPLE
    assert app.world is None and app.result is None
    app.pattern_text.set('9 × 6')
    app.apply_board()
    assert len(app.corners) == 40
    app.points = [[1100, 230], [1100, 2030]]
    app.update_measurement()
    assert app.result['board']['squares'] == [9, 6]
    app.pattern_text.set('10 x 7')
    app.apply_board()
    assert app.result is None and str(app.save['state']) == 'disabled'
    app.pattern_text.set('9 x 6')
    app.apply_board()
    assert app.result['measurements']['simple_scale']['height_cm'] == pytest.approx(180, abs=.3)
