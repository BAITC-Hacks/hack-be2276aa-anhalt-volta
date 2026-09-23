"""Native palette and component integration checks, no network or model calls."""
from pathlib import Path
import re
import tomllib


def contrast(a, b):
    def luminance(color):
        channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
        channels = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(channels, (.2126, .7152, .0722)))
    lo, hi = sorted((luminance(a), luminance(b)))
    return (hi + .05) / (lo + .05)


def test_native_palettes_and_dark_regression():
    theme = tomllib.loads(Path('.streamlit/config.toml').read_text())['theme']
    assert theme['base'] == 'dark'
    for key, value in {'primaryColor': '#38D9A9', 'backgroundColor': '#0B1018',
                       'secondaryBackgroundColor': '#151E2C', 'textColor': '#E7EDF5'}.items():
        assert theme['dark'][key] == value
    for name in ('dark', 'light'):
        palette = theme[name]
        for surface in ('backgroundColor', 'secondaryBackgroundColor'):
            assert contrast(palette['textColor'], palette[surface]) >= 7
            assert contrast(palette['primaryColor'], palette[surface]) >= 3


def test_avatar_light_text_contrast():
    light = Path('avatar_frontend/theme.css').read_text().split(':root[data-theme="light"]')[1].split('}')[0]
    tokens = dict(re.findall(r'--([\w-]+): (#[\da-f]{6});', light))
    for name in ('text-primary', 'label', 'summary', 'hint'):
        assert contrast(tokens[name], '#f5f7f8') >= 4.5, name
    assert contrast(tokens['input-text'], tokens['input-background']) >= 7
    assert contrast(tokens['status-text'], tokens['status-background']) >= 4.5


def test_component_registers_for_independent_sessions():
    from streamlit.testing.v1 import AppTest
    for _ in range(2):
        app = AppTest.from_file('app.py', default_timeout=20).run()
        assert not app.exception
        assert app.title[0].value == 'Sөile • Voice Router'
