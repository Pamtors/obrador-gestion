"""Gestión de clientes B2B (tabla clientes_b2b): ficha comercial, datos de facturación
y de entrega. Accesible para JEFES y ADMINISTRACION."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import joinedload

from app.auth.permisos import requiere_permiso
from app.database import SessionLocal
from app.models.cliente_b2b import ClienteB2B, MetodoEnvioFactura, TipoCliente, TipoDocumento
from app.models.pedido import Pedido
from app.plantillas import templates

router = APIRouter(prefix="/clientes")


@router.get("/", response_class=HTMLResponse)
@requiere_permiso("clientes")
async def listar_clientes(request: Request, q: str = ""):
    """Lista clientes B2B con búsqueda opcional por nombre comercial (?q=)."""
    db = SessionLocal()
    try:
        query = db.query(ClienteB2B).order_by(ClienteB2B.nombre_comercial)
        if q:
            query = query.filter(ClienteB2B.nombre_comercial.ilike(f"%{q}%"))
        clientes = query.all()
        return templates.TemplateResponse("clientes/lista.html", {
            "request": request, "usuario": request.state.usuario,
            "clientes": clientes, "q": q,
            "tipos_doc": TipoDocumento, "tipos_cliente": TipoCliente,
            "metodos_envio": MetodoEnvioFactura,
        })
    finally:
        db.close()


@router.post("/crear")
@requiere_permiso("clientes", editar=True)
async def crear_cliente(
    request: Request,
    nombre_comercial: str = Form(...),
    tipo_cliente: str = Form("B2B"),
    id_holded: str = Form(""),
    razon_social: str = Form(""),
    cif: str = Form(""),
    direccion_social: str = Form(""),
    direccion_entrega: str = Form(""),
    zona_ruta: str = Form(""),
    ventana_desde: str = Form(""),
    ventana_hasta: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    tipo_documento: str = Form("ALBARAN"),
    metodo_envio_factura: str = Form("N.A."),
    via_pago: str = Form(""),
    cuenta_bancaria: str = Form(""),
    comentarios: str = Form(""),
):
    """Crea un cliente B2B; id_holded enlaza con el contacto en Holded para facturar."""
    db = SessionLocal()
    try:
        db.add(ClienteB2B(
            nombre_comercial=nombre_comercial.strip(),
            tipo_cliente=TipoCliente(tipo_cliente),
            id_holded=id_holded.strip() or None,
            razon_social=razon_social.strip() or None,
            cif=cif.strip() or None,
            direccion_social=direccion_social.strip() or None,
            direccion_entrega=direccion_entrega.strip() or None,
            zona_ruta=zona_ruta.strip() or None,
            ventana_entrega_desde=ventana_desde.strip() or None,
            ventana_entrega_hasta=ventana_hasta.strip() or None,
            telefono=telefono.strip() or None,
            email=email.strip() or None,
            tipo_documento=TipoDocumento(tipo_documento),
            metodo_envio_factura=MetodoEnvioFactura(metodo_envio_factura),
            via_pago=via_pago.strip() or None,
            cuenta_bancaria=cuenta_bancaria.strip() or None,
            comentarios=comentarios.strip() or None,
        ))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/clientes/", status_code=302)


@router.get("/{id}", response_class=HTMLResponse)
@requiere_permiso("clientes")
async def ver_cliente(request: Request, id: int):
    """Ficha del cliente con su histórico de pedidos (tablas clientes_b2b y pedidos)."""
    db = SessionLocal()
    try:
        cliente = db.query(ClienteB2B).filter(ClienteB2B.id == id).first()
        if not cliente:
            return RedirectResponse(url="/clientes/", status_code=302)

        pedidos_raw = (
            db.query(Pedido)
            .options(joinedload(Pedido.lineas))
            .filter(Pedido.cliente_b2b_id == id)
            .order_by(Pedido.fecha_recogida.desc(), Pedido.id.desc())
            .all()
        )
        pedidos = [
            {
                "id": p.id,
                "referencia": p.referencia,
                "fecha_pedido": p.fecha_pedido,
                "fecha_recogida": p.fecha_recogida,
                "fecha_horneado": p.fecha_horneado,
                "total_lineas": sum(l.cantidad for l in p.lineas),
                "holded_doc_id": p.holded_doc_id,
            }
            for p in pedidos_raw
        ]

        return templates.TemplateResponse("clientes/detalle.html", {
            "request": request, "usuario": request.state.usuario,
            "cliente": cliente, "tipos_doc": TipoDocumento, "tipos_cliente": TipoCliente,
            "metodos_envio": MetodoEnvioFactura, "pedidos": pedidos,
        })
    finally:
        db.close()


@router.post("/{id}/editar")
@requiere_permiso("clientes", editar=True)
async def editar_cliente(
    request: Request, id: int,
    nombre_comercial: str = Form(...),
    tipo_cliente: str = Form("B2B"),
    id_holded: str = Form(""),
    razon_social: str = Form(""),
    cif: str = Form(""),
    direccion_social: str = Form(""),
    direccion_entrega: str = Form(""),
    zona_ruta: str = Form(""),
    ventana_desde: str = Form(""),
    ventana_hasta: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    tipo_documento: str = Form("ALBARAN"),
    metodo_envio_factura: str = Form("N.A."),
    via_pago: str = Form(""),
    cuenta_bancaria: str = Form(""),
    comentarios: str = Form(""),
):
    """Actualiza todos los campos de la ficha del cliente B2B."""
    db = SessionLocal()
    try:
        c = db.query(ClienteB2B).filter(ClienteB2B.id == id).first()
        if c:
            c.nombre_comercial = nombre_comercial.strip()
            c.tipo_cliente = TipoCliente(tipo_cliente)
            c.id_holded = id_holded.strip() or None
            c.razon_social = razon_social.strip() or None
            c.cif = cif.strip() or None
            c.direccion_social = direccion_social.strip() or None
            c.direccion_entrega = direccion_entrega.strip() or None
            c.zona_ruta = zona_ruta.strip() or None
            c.ventana_entrega_desde = ventana_desde.strip() or None
            c.ventana_entrega_hasta = ventana_hasta.strip() or None
            c.telefono = telefono.strip() or None
            c.email = email.strip() or None
            c.tipo_documento = TipoDocumento(tipo_documento)
            c.metodo_envio_factura = MetodoEnvioFactura(metodo_envio_factura)
            c.via_pago = via_pago.strip() or None
            c.cuenta_bancaria = cuenta_bancaria.strip() or None
            c.comentarios = comentarios.strip() or None
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/clientes/{id}", status_code=302)


@router.post("/{id}/toggle")
@requiere_permiso("clientes", editar=True)
async def toggle_cliente(request: Request, id: int):
    """Activa/desactiva el cliente (baja lógica; deja de aparecer al crear pedidos)."""
    db = SessionLocal()
    try:
        c = db.query(ClienteB2B).filter(ClienteB2B.id == id).first()
        if c:
            c.activo = not c.activo
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/clientes/", status_code=302)
