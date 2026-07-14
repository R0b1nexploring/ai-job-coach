from app.errors import AppError


class DisabledPaymentProvider:
    """MVP-1 payment placeholder. It never simulates successful money movement."""

    async def create_payment(self, order):
        raise AppError("PAYMENT_NOT_AVAILABLE", "在线支付尚未开放。", 501)

    async def verify_webhook(self, headers, body):
        raise AppError("PAYMENT_NOT_AVAILABLE", "支付回调尚未开放。", 501)

    async def refund(self, order, amount_cents: int):
        raise AppError("PAYMENT_NOT_AVAILABLE", "在线退款尚未开放。", 501)
