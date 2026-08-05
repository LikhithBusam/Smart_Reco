from datetime import datetime

from pydantic import BaseModel

from app.schemas.product import ProductResponse


class RecommendationOut(BaseModel):
    narrative: str | None
    products: list[ProductResponse]
    generated_at: datetime | None
