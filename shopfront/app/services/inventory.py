from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundError
from app.models import Product


async def restock_product(db: AsyncSession, product_id: int, quantity: int) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found")

    product.stock += quantity
    await db.commit()
    return product
