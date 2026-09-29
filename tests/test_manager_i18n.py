"""Язык меняется без переимпорта менеджеров; обработчики ошибок сохраняют типы."""
import pytest

from modules import i18n, shareconfig, upstream
from modules import errors


@pytest.mark.parametrize(('error_type', 'standard_type'), [
    (errors.ChimeraValueError, ValueError),
    (errors.ChimeraRuntimeError, RuntimeError),
    (errors.ChimeraOSError, OSError),
    (errors.ChimeraPermissionError, PermissionError),
    (errors.ChimeraFileNotFoundError, FileNotFoundError),
    (errors.ChimeraKeyError, KeyError),
])
def test_localized_errors_preserve_exception_contract(error_type, standard_type):
    with i18n.using('en'):
        error = error_type('err.url.http_only')
        assert isinstance(error, standard_type)
        assert errors.describe(error)['code'] == 'err.url.http_only'
        assert str(error) == i18n.translate('ru', error.code)
        assert error.message() == i18n.translate('en', error.code)


def test_manager_labels_follow_current_language_without_reload():
    with i18n.using('ru'):
        title = shareconfig.TITLES['lists']
        source = upstream._SOURCES[1]['name']
    with i18n.using('en'):
        assert shareconfig.TITLES['lists'] != title
        assert upstream._SOURCES[1]['name'] != source
    with i18n.using('ru'):
        assert shareconfig.TITLES['lists'] == title
        assert upstream._SOURCES[1]['name'] == source
