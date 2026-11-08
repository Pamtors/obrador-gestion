"""Cliente HTTP de la API de Holded. Soporta las dos versiones de la API:
v1 (clave clásica de 32 hex, header "key", fechas unix, camelCase) y
v2 (token pat_/sk_, header "Authorization: Bearer", fechas ISO, snake_case).
La versión se auto-detecta por el prefijo de la clave en es_clave_v2()."""
from datetime import date, datetime

import requests

_V1_BASE = "https://api.holded.com/api/invoicing/v1"
_V2_BASE = "https://api.holded.com/api/v2"

_V2_DOC_ENDPOINT = {
    "waybill": "waybills",
    "invoice": "invoices",
}

_VAT_FIELDS_V1 = ["tin", "vatnumber", "taxId", "nif", "vat", "taxid", "fiscalId"]
_VAT_FIELDS_V2 = ["vat_number", "tin", "nif"]

# Código de IVA 10% en Holded España
_IVA_10_CODE = "s_iva_10"


def es_clave_v2(api_key: str) -> bool:
    """True si la clave es de la API v2 (tokens PAT o sk_); si no, es clave clásica v1."""
    return api_key.startswith(("pat_", "sk_live_", "sk_test_"))


def _headers(api_key: str) -> dict:
    """Auth según versión: v2 usa Bearer token, v1 el header propietario 'key'."""
    if es_clave_v2(api_key):
        return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    return {"key": api_key}


# ── Crear documento ───────────────────────────────────────────────────────────

def crear_documento(
    api_key: str,
    contact_id: str,
    fecha: date,
    numero: str,
    items: list[dict],
    doc_tipo: str = "waybill",
) -> str:
    """Crea un documento (waybill=albarán, invoice=factura) en Holded y devuelve su id.
    Enruta a v1 o v2 según el tipo de clave."""
    if es_clave_v2(api_key):
        return _crear_v2(api_key, contact_id, fecha, numero, items, doc_tipo)
    return _crear_v1(api_key, contact_id, fecha, numero, items, doc_tipo)


def _crear_v1(api_key, contact_id, fecha, numero, items, doc_tipo) -> str:
    """Crea el documento vía API v1: fechas en timestamp unix, items en formato v1."""
    fecha_unix = int(datetime(fecha.year, fecha.month, fecha.day).timestamp())
    payload = {
        "contactId": contact_id,
        "date": fecha_unix,
        "dueDate": fecha_unix,
        "docNumber": numero,
        "items": items,  # formato v1: {name, desc, units, subtotal, tax}
    }
    r = requests.post(
        f"{_V1_BASE}/documents/{doc_tipo}",
        headers={**_headers(api_key), "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    _check_response(r)
    result = r.json()
    # v1 responde 200 aunque falle: el éxito real lo indica status == 1
    if result.get("status") != 1:
        raise ValueError(f"Holded rechazó el documento: {str(result.get('info', 'sin detalle'))[:200]}")
    return result["id"]


def _crear_v2(api_key, contact_id, fecha, numero, items, doc_tipo) -> str:
    """Crea el documento vía API v2: fechas ISO, campos snake_case, IVA por código de tax."""
    # v2 usa el plural como endpoint (waybill → waybills, invoice → invoices)
    endpoint = _V2_DOC_ENDPOINT.get(doc_tipo, doc_tipo)
    # Convertir items del formato interno al formato v2
    lines_v2 = [
        {
            "name": it["name"],
            "description": it.get("desc", ""),
            "price": float(it["subtotal"]),   # subtotal = precio unitario
            "units": float(it["units"]),
            "taxes": [_IVA_10_CODE],
        }
        for it in items
    ]
    payload = {
        "contact_id": contact_id,
        "date": fecha.isoformat(),
        "due_date": fecha.isoformat(),
        "document_number": numero,
        "items": lines_v2,
    }
    r = requests.post(
        f"{_V2_BASE}/{endpoint}",
        headers={**_headers(api_key), "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    _check_response(r)
    result = r.json()
    # El id puede venir como "id" o "_id" según el endpoint
    doc_id = result.get("id") or result.get("_id")
    if not doc_id:
        raise ValueError(f"Holded v2 no devolvió ID del documento: {str(result)[:200]}")
    return doc_id


# ── Items ─────────────────────────────────────────────────────────────────────

def construir_items(lineas: list[dict]) -> list[dict]:
    """
    Formato interno compartido por v1 y v2.
    subtotal = precio UNITARIO. v1 lo usa directamente; v2 lo convierte a price.
    """
    return [
        {
            "name": f"{l['sabor_nombre']} {l['tamano_nombre']}",
            "desc": "",
            "units": float(l["cantidad"]),
            "subtotal": float(l["precio_franquicia"]),
            "tax": 10,
        }
        for l in lineas
    ]


# ── Contactos ─────────────────────────────────────────────────────────────────

def obtener_contactos_holded(api_key: str) -> list[dict]:
    """Descarga todos los contactos de Holded (paginando) con la versión de API que toque."""
    if es_clave_v2(api_key):
        return _contactos_v2(api_key)
    return _contactos_v1(api_key)


def _contactos_v1(api_key: str) -> list[dict]:
    """v1 pagina por número de página; una página con menos de 500 items es la última."""
    all_contacts: list[dict] = []
    page = 1
    while True:
        r = requests.get(
            f"{_V1_BASE}/contacts",
            headers=_headers(api_key),
            params={"page": page},
            timeout=15,
        )
        _check_response(r)
        data = _parse_json(r)
        if not isinstance(data, list) or not data:
            break
        all_contacts.extend(data)
        if len(data) < 500:
            break
        page += 1
    return all_contacts


def _contactos_v2(api_key: str) -> list[dict]:
    # v2 paginación por cursor: {"items":[...], "cursor":"...", "has_more":bool}
    all_contacts: list[dict] = []
    cursor = None
    while True:
        params: dict = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(
            f"{_V2_BASE}/contacts",
            headers=_headers(api_key),
            params=params,
            timeout=15,
        )
        _check_response(r)
        data = _parse_json(r)
        items = data.get("items", []) if isinstance(data, dict) else data
        if not items:
            break
        all_contacts.extend(items)
        if not data.get("has_more"):
            break
        cursor = data.get("cursor")
    return all_contacts


def normalizar_contacto(c: dict) -> dict:
    """Extrae campos útiles de un contacto Holded (v1 camelCase o v2 snake_case)."""
    # CIF: v2 usa vat_number, v1 usaba vatnumber/taxId/etc.
    cif = ""
    for f in _VAT_FIELDS_V2 + _VAT_FIELDS_V1:
        val = (c.get(f) or "").strip()
        if val:
            cif = val
            break
    if not cif:
        bill = c.get("bill_address") or c.get("billAddress") or {}
        if isinstance(bill, dict):
            for f in _VAT_FIELDS_V2 + _VAT_FIELDS_V1:
                val = (bill.get(f) or "").strip()
                if val:
                    cif = val
                    break
    return {
        "id_holded": c.get("id", ""),
        "nombre": (c.get("name") or c.get("trade_name") or c.get("tradeName") or "").strip(),
        "cif": cif,
        "email": (c.get("email") or "").strip(),
        "telefono": (c.get("phone") or c.get("mobile") or "").strip(),
        # type de Holded: client / supplier / lead / debtor / creditor
        "tipo": (c.get("type") or "").strip().lower(),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(r: requests.Response):
    try:
        return r.json()
    except Exception:
        raise ConnectionError(
            f"Holded devolvió una respuesta no-JSON. "
            f"Primeros 200 chars: {r.text[:200]}"
        )


def _check_response(r: requests.Response) -> None:
    """Traduce errores HTTP de Holded a excepciones con mensajes accionables para el usuario."""
    if r.status_code == 401:
        raise PermissionError("Token de Holded inválido o expirado.")
    if r.status_code == 403:
        raise PermissionError(
            "Sin permisos en Holded (403). "
            "El token necesita los scopes: contacts (lectura), sales/invoices y sales/albaranes (escritura). "
            "Genera un nuevo token en Holded → Ajustes → API con todos los permisos."
        )
    if r.status_code == 404:
        raise ConnectionError(
            f"Endpoint no encontrado en Holded (404). "
            f"URL: {r.url}"
        )
    if r.status_code == 429:
        raise ConnectionError("Límite de peticiones de Holded alcanzado. Espera unos segundos.")
    if r.status_code >= 500:
        raise ConnectionError(f"Error del servidor de Holded ({r.status_code}).")
    if r.status_code == 400:
        try:
            body = r.json()
        except Exception:
            body = {}
        # Caso típico: usar clave de una versión contra la API de la otra
        if body.get("info") == "Invalid key":
            raise PermissionError(
                "Clave de Holded rechazada. "
                "Usa una clave clásica (32 hex) para la API v1, "
                "o un token PAT (pat_...) para la API v2."
            )
        raise ConnectionError(f"Error de Holded (400): {r.text[:200]}")
    if r.status_code not in (200, 201):
        raise ConnectionError(f"Respuesta inesperada de Holded ({r.status_code}).")
