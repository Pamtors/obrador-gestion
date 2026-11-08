"""Hashing y verificación de contraseñas con bcrypt."""
import bcrypt


def hashear(contrasena: str) -> str:
    """Genera el hash bcrypt de una contraseña en claro (para guardar en usuarios.hash_contrasena)."""
    return bcrypt.hashpw(contrasena.encode(), bcrypt.gensalt()).decode()


def verificar(contrasena: str, hash_: str) -> bool:
    """Comprueba si la contraseña en claro coincide con el hash almacenado."""
    return bcrypt.checkpw(contrasena.encode(), hash_.encode())
