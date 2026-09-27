from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors import CheckoutError, InvalidStateError, NotFoundError
from app.routers import admin, customers, orders, products

app = FastAPI(title="Shopfront API", version="0.3.0")

app.include_router(customers.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(admin.router)


@app.exception_handler(NotFoundError)
async def not_found(_: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(CheckoutError)
async def checkout_failed(_: Request, exc: CheckoutError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(InvalidStateError)
async def invalid_state(_: Request, exc: InvalidStateError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/health")
async def health():
    return {"status": "ok"}
