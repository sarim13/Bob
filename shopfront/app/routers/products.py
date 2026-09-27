from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import ProductOut, RestockIn, StockOut
from app.services.catalog import catalog
from app.services.inventory import restock_product

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/search", response_model=list[ProductOut])
async def search_products(q: str = Query(min_length=1), limit: int = Query(20, le=100)):
    products = await catalog.search(q, limit=limit)
    return [ProductOut.model_validate(p) for p in products]


@router.post("/{product_id}/restock", response_model=StockOut)
async def restock(product_id: int, body: RestockIn, db: AsyncSession = Depends(get_db)):
    product = await restock_product(db, product_id, body.quantity)
    return StockOut(id=product.id, stock=product.stock)
