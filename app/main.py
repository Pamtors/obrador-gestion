"""Punto de entrada de la aplicación FastAPI: monta estáticos y registra todos los routers.
Se arranca con: uvicorn app.main:app"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth, catalogo, clientes, franquicias, holded, imprimir, inicio, pedidos, produccion, stock, tiendas, usuarios

# docs_url/redoc_url desactivados: la API no se expone públicamente como REST documentada
app = FastAPI(title="Obrador Demo — Sistema de Gestión", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(inicio.router)
app.include_router(usuarios.router)
app.include_router(catalogo.router)
app.include_router(tiendas.router)
app.include_router(clientes.router)
app.include_router(pedidos.router)
app.include_router(imprimir.router)
app.include_router(produccion.router)
app.include_router(holded.router)
app.include_router(stock.router)
app.include_router(franquicias.router)
