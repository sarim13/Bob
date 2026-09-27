from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)


class SignupOut(BaseModel):
    email: EmailStr
    name: str


class NewsletterOut(BaseModel):
    customer_id: int
    newsletter_opt_in: bool


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    price: Decimal
    stock: int


class RestockIn(BaseModel):
    quantity: int = Field(gt=0)


class StockOut(BaseModel):
    id: int
    stock: int


class CheckoutItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


class CheckoutIn(BaseModel):
    customer_id: int
    items: list[CheckoutItem] = Field(min_length=1)
    coupon_code: str | None = None


class OrderCreated(BaseModel):
    id: int
    status: str
    total: Decimal


class OrderLine(BaseModel):
    product_id: int
    quantity: int
    unit_price: Decimal


class OrderDetail(BaseModel):
    id: int
    status: str
    total: Decimal
    customer_email: EmailStr
    items: list[OrderLine]


class ShipIn(BaseModel):
    carrier: str = "dhl"


class ShipOut(BaseModel):
    id: int
    status: str


class DashboardOut(BaseModel):
    customers: int
    orders: int
    revenue: Decimal


class ReportRequest(BaseModel):
    day: date | None = None
