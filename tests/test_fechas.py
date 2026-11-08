"""Las fechas se muestran en español sin depender del locale del sistema."""
from datetime import date, datetime

from app.fechas import fecha_es


def test_dia_y_mes_en_espanol():
    # 2026-08-03 es lunes; antes salía "MONDAY 03 DE AUGUST DE 2026"
    assert fecha_es(date(2026, 8, 3), "%A %d de %B de %Y") == "lunes 03 de agosto de 2026"


def test_upper_y_capitalize_como_en_las_plantillas():
    f = date(2026, 8, 3)
    assert fecha_es(f, "%A %d de %B de %Y").upper() == "LUNES 03 DE AGOSTO DE 2026"
    assert fecha_es(f, "%A %d de %B de %Y").capitalize() == "Lunes 03 de agosto de 2026"


def test_codigos_no_locale_se_delegan_en_strftime():
    assert fecha_es(date(2026, 8, 3), "%A %d/%m/%Y") == "lunes 03/08/2026"
    assert fecha_es(datetime(2026, 12, 25, 14, 30), "%A %H:%M") == "viernes 14:30"


def test_abreviaturas_y_porcentaje_literal():
    assert fecha_es(date(2026, 8, 3), "%a %d %b") == "lun 03 ago"
    assert fecha_es(date(2026, 8, 3), "100%% el %A") == "100% el lunes"


def test_todos_los_dias_y_meses():
    assert [fecha_es(date(2026, 8, d), "%A") for d in range(3, 10)] == [
        "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    assert [fecha_es(date(2026, m, 1), "%B") for m in range(1, 13)] == [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def test_none_no_revienta():
    assert fecha_es(None) == ""
