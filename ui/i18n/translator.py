# -*- coding: utf-8 -*-
"""
Translator — JSON-based i18n for the Assessment Wizard plugin.

Strings live in ``translations/{en,es,pt,de}.json`` and are addressed with
dot-notation keys (``section.key``). The language is, in order of priority:

  1. the one the user picked in the panel's language selector (persisted in
     QgsSettings under ``q_assessment_wizard/language``),
  2. the QGIS UI locale,
  3. English.

Usage
-----
    from .translator import tr, set_language

    title = tr('main.btn_new_project')
    msg   = tr('main.delete_assessment_body', name='forest_2024')
    set_language('es')   # switch at runtime and remember the choice

Missing keys return the key itself, so a missing translation never breaks the UI.
Widgets that must follow runtime language switches re-apply their texts in a
``retranslateUi()`` method.
"""

import json
import os

_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), 'translations')
_SETTINGS_KEY = 'q_assessment_wizard/language'
_DEFAULT = 'en'

# Display names shown in the language selector (each in its own language).
LANGUAGES = {
    'en': 'English',
    'es': 'Español',
    'pt': 'Português',
    'de': 'Deutsch',
}


def _settings():
    try:
        from qgis.core import QgsSettings
        return QgsSettings()
    except Exception:
        return None


class _Translator:

    def __init__(self):
        self._data = {}
        self._lang = _DEFAULT
        self.load(self._detect())

    @staticmethod
    def _detect():
        settings = _settings()
        if settings is None:
            return _DEFAULT
        saved = str(settings.value(_SETTINGS_KEY, '') or '')
        if saved in LANGUAGES:
            return saved
        lang = str(settings.value('locale/userLocale', 'en_US') or 'en_US')[:2].lower()
        return lang if lang in LANGUAGES else _DEFAULT

    def load(self, lang):
        """Load the JSON file for *lang*; falls back to English."""
        if lang not in LANGUAGES:
            lang = _DEFAULT
        path = os.path.join(_TRANSLATIONS_DIR, f'{lang}.json')
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                self._data = json.load(fh)
            self._lang = lang
        except (OSError, ValueError):
            self._data = {}

    def t(self, key, **kwargs):
        node = self._data
        for part in key.split('.'):
            node = node.get(part, '') if isinstance(node, dict) else ''
        text = node if isinstance(node, str) else ''
        if text and kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError, IndexError):
                pass
        return text or key


_translator = _Translator()


def tr(key, **kwargs):
    """Return the translated string for *key* (dot-notation)."""
    return _translator.t(key, **kwargs)


def set_language(lang, persist=True):
    """Switch the active language at runtime (and remember it by default)."""
    _translator.load(lang)
    if persist:
        settings = _settings()
        if settings is not None:
            settings.setValue(_SETTINGS_KEY, _translator._lang)


def get_language():
    """Return the two-letter code of the active language."""
    return _translator._lang
