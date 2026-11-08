"""Tokens de sesión firmados con itsdangerous (sin estado en BD).
El token solo contiene el id del usuario, firmado con la SECRET_KEY y con caducidad."""
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import config

_serializer = URLSafeTimedSerializer(config.secret_key)
_DURACION_SESION = 60 * 60 * 8  # 8 horas


def crear_token_sesion(usuario_id: int) -> str:
    """Firma el id de usuario y devuelve el token que se guarda en la cookie de sesión."""
    return _serializer.dumps(usuario_id, salt="sesion")


def leer_token_sesion(token: str) -> int | None:
    """Devuelve el usuario_id del token, o None si está caducado (>8h) o manipulado."""
    try:
        return _serializer.loads(token, salt="sesion", max_age=_DURACION_SESION)
    except (SignatureExpired, BadSignature):
        return None
