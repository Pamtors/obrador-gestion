"""Formato de fechas en español sin depender del locale del sistema operativo.

`strftime('%A')` / `strftime('%B')` devuelven el día y el mes en el idioma que
tenga configurado el proceso, y en ningún punto de la app se hace `setlocale`:
en Docker, CI o Windows salían en inglés ("MONDAY 03 DE AUGUST DE 2026").
`fecha_es` traduce %A/%a/%B/%b con un diccionario propio y delega el resto de
códigos en `strftime`, así que el resultado es siempre el mismo en cualquier
despliegue.

Está registrado como filtro Jinja `fecha_es` en app/plantillas.py:
    {{ fecha | fecha_es('%A %d de %B de %Y') | upper }}
"""
from datetime import date, datetime

# En español los días y los meses van en minúscula; quien necesite otra caja
# aplica |upper o |capitalize sobre el resultado.
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def fecha_es(fecha: date | datetime | None, formato: str = "%A %d de %B de %Y") -> str:
    """Formatea `fecha` con los nombres de día y mes en español.

    Acepta los mismos códigos que `strftime`; %A/%a/%B/%b se traducen aquí y
    el resto se delega en `strftime`. Devuelve "" si `fecha` es None para que
    las plantillas no revienten con fechas opcionales.
    """
    if fecha is None:
        return ""

    partes: list[str] = []
    i = 0
    while i < len(formato):
        if formato[i] == "%" and i + 1 < len(formato):
            codigo = formato[i + 1]
            if codigo == "A":
                partes.append(DIAS[fecha.weekday()])
            elif codigo == "a":
                partes.append(DIAS[fecha.weekday()][:3])
            elif codigo == "B":
                partes.append(MESES[fecha.month - 1])
            elif codigo == "b":
                partes.append(MESES[fecha.month - 1][:3])
            else:
                partes.append(fecha.strftime("%" + codigo))
            i += 2
            continue
        partes.append(formato[i])
        i += 1
    return "".join(partes)
