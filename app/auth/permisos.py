"""Control de acceso por matriz de permisos: 8 puestos (tabla usuarios) con niveles
NADA/VER/EDITAR por servicio y subapartado. Decoradores: requiere_permiso(clave,
editar=...) y requiere_sesion. El puesto TIENDAS queda además limitado a su tienda_id
en los endpoints (ámbito aplicado en app/api/pedidos.py y app/api/stock.py)."""
import enum
from dataclasses import dataclass
from functools import wraps
from typing import Callable

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session, joinedload

from app.auth.sesion import leer_token_sesion
from app.database import SessionLocal
from app.models.usuario import Rol, Usuario

COOKIE_SESION = "sesion"


class Nivel(enum.IntEnum):
    """Nivel de acceso a un servicio/subapartado."""
    NADA = 0
    VER = 1      # consulta: GET sí, POST no, sin botones de edición
    EDITAR = 2


_TODO_JEFES = {"clientes": Nivel.EDITAR, "pedidos": Nivel.EDITAR, "pedidos.rutas": Nivel.EDITAR,
               "impresion": Nivel.EDITAR, "stock": Nivel.EDITAR, "produccion": Nivel.EDITAR,
               "holded": Nivel.EDITAR, "catalogo": Nivel.EDITAR, "admin": Nivel.EDITAR,
               "franquicias": Nivel.EDITAR}

# Matriz de permisos (docs/PERMISOS_SPEC.md). Clave = "servicio" o "servicio.subapartado".
# Resolución: clave exacta > clave del servicio > NADA.
PERMISOS: dict[Rol, dict[str, Nivel]] = {
    Rol.VISUALIZADOR: {
        "clientes": Nivel.VER,
        "pedidos": Nivel.VER,
        "pedidos.rutas": Nivel.VER,
        "impresion": Nivel.VER,
        "stock": Nivel.VER,
        "produccion": Nivel.VER,
        "holded": Nivel.VER,
        "catalogo": Nivel.VER,
        "franquicias": Nivel.VER,
    },
    Rol.JEFES: dict(_TODO_JEFES),
    Rol.ADMINISTRACION: {**_TODO_JEFES, "admin": Nivel.NADA},
    Rol.REPARTIDORES: {
        "pedidos.rutas": Nivel.EDITAR,
        "impresion": Nivel.EDITAR,
        "stock.envios": Nivel.EDITAR,
    },
    Rol.PASTELERAS: {
        "pedidos": Nivel.VER,
        "pedidos.rutas": Nivel.NADA,
        "impresion": Nivel.EDITAR,
        "stock.partes": Nivel.EDITAR,
        "stock.envios": Nivel.EDITAR,
        "stock.dias_reparto": Nivel.VER,
        "produccion": Nivel.EDITAR,
        "franquicias": Nivel.EDITAR,
    },
    Rol.JEFE_PASTELEROS: {
        "pedidos": Nivel.EDITAR, "pedidos.rutas": Nivel.EDITAR,
        "impresion": Nivel.EDITAR, "stock": Nivel.EDITAR,
        "produccion": Nivel.EDITAR, "catalogo": Nivel.EDITAR,
        "franquicias": Nivel.EDITAR,
    },
    Rol.TIENDAS: {  # además, todo limitado a su tienda_id (se aplica en los endpoints)
        "pedidos": Nivel.VER,
        "pedidos.rutas": Nivel.NADA,
        "stock.partes": Nivel.EDITAR,
        "stock.envios": Nivel.EDITAR,
        "stock.mermas": Nivel.EDITAR,
        "stock.dias_reparto": Nivel.VER,
        "franquicias": Nivel.VER,
    },
    Rol.AREA_MANAGER: {"pedidos": Nivel.EDITAR, "pedidos.rutas": Nivel.EDITAR,
                       "stock": Nivel.EDITAR},
    Rol.COMERCIAL: {"clientes": Nivel.EDITAR, "pedidos": Nivel.EDITAR,
                    "pedidos.rutas": Nivel.NADA},
}


def nivel_permiso(rol: Rol, clave: str) -> Nivel:
    """Nivel de un rol para una clave: exacta > servicio > NADA."""
    permisos = PERMISOS.get(rol, {})
    if clave in permisos:
        return permisos[clave]
    servicio = clave.split(".")[0]
    return permisos.get(servicio, Nivel.NADA)


@dataclass
class UsuarioSesion:
    """Versión simple del usuario para usar en plantillas, sin dependencia de BD."""
    id: int
    nombre: str
    email: str
    rol: Rol
    activo: bool
    tienda_id: int | None
    tienda_nombre: str | None

    @property
    def tienda(self):
        if self.tienda_nombre:
            return type("Tienda", (), {"nombre": self.tienda_nombre})()
        return None

    @property
    def rol_nombre(self) -> str:
        from app.models.usuario import ROL_NOMBRES
        return ROL_NOMBRES.get(self.rol, self.rol.value)

    def puede(self, clave: str) -> bool:
        return nivel_permiso(self.rol, clave) >= Nivel.VER

    def puede_editar(self, clave: str) -> bool:
        return nivel_permiso(self.rol, clave) >= Nivel.EDITAR

    def puede_servicio(self, servicio: str) -> bool:
        """True si tiene acceso al servicio o a ALGÚN subapartado (para el menú)."""
        permisos = PERMISOS.get(self.rol, {})
        if permisos.get(servicio, Nivel.NADA) >= Nivel.VER:
            return True
        return any(k.startswith(servicio + ".") and n >= Nivel.VER
                   for k, n in permisos.items())


def obtener_usuario_actual(request: Request) -> UsuarioSesion | None:
    """Lee la cookie de sesión, valida el token y carga el usuario desde la tabla usuarios.
    Devuelve None si no hay sesión válida o el usuario está inactivo."""
    token = request.cookies.get(COOKIE_SESION)
    if not token:
        return None
    usuario_id = leer_token_sesion(token)
    if not usuario_id:
        return None
    db: Session = SessionLocal()
    try:
        u = db.query(Usuario).options(joinedload(Usuario.tienda)).filter(
            Usuario.id == usuario_id, Usuario.activo == True
        ).first()
        if not u:
            return None
        return UsuarioSesion(
            id=u.id,
            nombre=u.nombre,
            email=u.email,
            rol=u.rol,
            activo=u.activo,
            tienda_id=u.tienda_id,
            tienda_nombre=u.tienda.nombre if u.tienda else None,
        )
    finally:
        db.close()


def requiere_sesion(func: Callable) -> Callable:
    """Solo exige estar autenticado (para la página de inicio)."""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        usuario = obtener_usuario_actual(request)
        if not usuario:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/login", status_code=302)
        request.state.usuario = usuario
        return await func(request, *args, **kwargs)
    return wrapper


def requiere_permiso(clave: str, editar: bool = False) -> Callable:
    """Exige nivel VER (o EDITAR si editar=True) para la clave de permiso.
    Sin sesión → redirect a /login; nivel insuficiente → 403.
    Deja el usuario disponible en request.state.usuario."""
    minimo = Nivel.EDITAR if editar else Nivel.VER

    def decorador(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            usuario = obtener_usuario_actual(request)
            if not usuario:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(url="/login", status_code=302)
            if nivel_permiso(usuario.rol, clave) < minimo:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tienes permiso para acceder a esta sección.",
                )
            request.state.usuario = usuario
            return await func(request, *args, **kwargs)
        return wrapper
    return decorador
