"""Persistent browser avatar; no LLM dependency and no per-frame Python work."""
from pathlib import Path
from streamlit.components.v1 import declare_component

_component = declare_component('soile_avatar', path=str(Path(__file__).parent / 'avatar_frontend'))


def render_avatar(reply='', language='ru', reply_id='', state='idle', audio=None, reset_id=0,
                  reaction=None, reaction_id=''):
    return _component(reply=reply, language=language, reply_id=reply_id, state=state,
                      audio=audio, reset_id=reset_id, reaction=reaction, reaction_id=reaction_id,
                      key='soile_avatar', default=None)
