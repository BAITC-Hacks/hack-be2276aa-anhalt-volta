"""Per-browser themes. Never mutate Streamlit's process-global configuration."""
from pathlib import Path

import streamlit as st
from streamlit.components.v2 import component

_assets = Path(__file__).parent / 'theme_frontend'


def render_theme_switch():
    # Loaded before app content. CSS-only entry goes into Streamlit's event container.
    css = '\n'.join((_assets / name).read_text(encoding='utf-8')
                    for name in ('theme.css', 'ambient.css', 'layout.css'))
    st.html(f'<style>{css}</style>')
    # Register in the current runtime (also supports independent AppTest sessions).
    _switch = component('soile_theme', js=(_assets / 'switch.js').read_text(encoding='utf-8'),
                        isolate_styles=False)
    _switch(key='soile_theme', height=0,
            data={'ambient': (_assets / 'ambient.html').read_text(encoding='utf-8')})
