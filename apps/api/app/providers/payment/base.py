from dataclasses import dataclass
from typing import Protocol


@dataclass
class PaymentEvent:
    event_id: str
    order_id: str
    provider_order_id: str
    amount_cents: int
    currency: str
    status: str


class PaymentProvider(Protocol):
    async def create_payment(self, order): ...
    async def verify_webhook(self, headers, body) -> PaymentEvent: ...
    async def refund(self, order, amount_cents: int): ...

