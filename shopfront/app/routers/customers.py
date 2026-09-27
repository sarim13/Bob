from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.errors import NotFoundError
from app.models import Customer, NewsletterSync
from app.schemas import NewsletterOut, SignupIn, SignupOut

router = APIRouter(tags=["customers"])


@router.post("/signup", response_model=SignupOut, status_code=201)
async def signup(body: SignupIn, db: AsyncSession = Depends(get_db)):
    customer = Customer(email=body.email.lower(), name=body.name.strip())
    db.add(customer)
    return SignupOut(email=customer.email, name=customer.name)


@router.post("/customers/{customer_id}/newsletter", response_model=NewsletterOut)
async def subscribe_newsletter(customer_id: int, db: AsyncSession = Depends(get_db)):
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found")

    try:
        async with db.begin_nested():
            db.add(NewsletterSync(customer_id=customer_id, provider="mailwave"))
            await db.flush()
    except IntegrityError:
        pass

    customer.newsletter_opt_in = True
    await db.commit()
    return NewsletterOut(customer_id=customer_id, newsletter_opt_in=True)
