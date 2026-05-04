from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal


class BalanceError(Exception):
    pass


@dataclass(frozen=True)
class Balance:
    user_telegram_id: int
    available: Decimal
    updated_at: datetime


@dataclass(frozen=True)
class LedgerEntry:
    id: str
    user_telegram_id: int
    kind: str
    amount: Decimal
    balance_after: Decimal
    reason: str
    order_id: str | None
    created_at: datetime


class InMemoryBalanceRepository:
    def __init__(self) -> None:
        self._balances: dict[int, Balance] = {}

    def get(self, user_telegram_id: int) -> Balance:
        balance = self._balances.get(user_telegram_id)
        if balance is not None:
            return balance

        return Balance(
            user_telegram_id=user_telegram_id,
            available=Decimal("0.00"),
            updated_at=datetime.now(UTC),
        )

    def get_available(self, user_telegram_id: int) -> Decimal:
        return self.get(user_telegram_id).available

    def save(self, balance: Balance) -> Balance:
        self._balances[balance.user_telegram_id] = balance
        return balance


class InMemoryLedgerRepository:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._next_id = 1

    def next_id(self) -> str:
        entry_id = f"ledger-{self._next_id}"
        self._next_id += 1
        return entry_id

    def save(self, entry: LedgerEntry) -> LedgerEntry:
        self._entries.append(entry)
        return entry

    def list_for_user(self, user_telegram_id: int) -> list[LedgerEntry]:
        return [
            entry
            for entry in self._entries
            if entry.user_telegram_id == user_telegram_id
        ]

    def find_order_charge(
        self,
        *,
        user_telegram_id: int,
        order_id: str,
    ) -> LedgerEntry | None:
        return self._find_order_entry(
            user_telegram_id=user_telegram_id,
            order_id=order_id,
            kind="order_charge",
        )

    def find_order_refund(
        self,
        *,
        user_telegram_id: int,
        order_id: str,
    ) -> LedgerEntry | None:
        return self._find_order_entry(
            user_telegram_id=user_telegram_id,
            order_id=order_id,
            kind="refund",
        )

    def _find_order_entry(
        self,
        *,
        user_telegram_id: int,
        order_id: str,
        kind: str,
    ) -> LedgerEntry | None:
        for entry in self._entries:
            if (
                entry.user_telegram_id == user_telegram_id
                and entry.order_id == order_id
                and entry.kind == kind
            ):
                return entry
        return None


def adjust_balance(
    *,
    balances: InMemoryBalanceRepository,
    ledger: InMemoryLedgerRepository,
    user_telegram_id: int,
    amount: Decimal,
    reason: str,
) -> LedgerEntry:
    if amount == Decimal("0"):
        raise BalanceError("Balance adjustment amount must not be zero")

    return _apply_ledger_entry(
        balances=balances,
        ledger=ledger,
        user_telegram_id=user_telegram_id,
        kind="admin_adjustment",
        amount=_money(amount),
        reason=reason,
        order_id=None,
    )


def charge_order(
    *,
    balances: InMemoryBalanceRepository,
    ledger: InMemoryLedgerRepository,
    user_telegram_id: int,
    order_id: str,
    amount: Decimal,
) -> LedgerEntry:
    existing = ledger.find_order_charge(
        user_telegram_id=user_telegram_id,
        order_id=order_id,
    )
    if existing is not None:
        return existing

    charge_amount = _money(amount)
    if charge_amount <= Decimal("0.00"):
        raise BalanceError("Order charge amount must be positive")

    current_balance = balances.get_available(user_telegram_id)
    if current_balance < charge_amount:
        raise BalanceError("Insufficient balance")

    return _apply_ledger_entry(
        balances=balances,
        ledger=ledger,
        user_telegram_id=user_telegram_id,
        kind="order_charge",
        amount=-charge_amount,
        reason="translation order charge",
        order_id=order_id,
    )


def refund_order(
    *,
    balances: InMemoryBalanceRepository,
    ledger: InMemoryLedgerRepository,
    user_telegram_id: int,
    order_id: str,
    reason: str,
) -> LedgerEntry:
    existing = ledger.find_order_refund(
        user_telegram_id=user_telegram_id,
        order_id=order_id,
    )
    if existing is not None:
        return existing

    charge = ledger.find_order_charge(
        user_telegram_id=user_telegram_id,
        order_id=order_id,
    )
    if charge is None:
        raise BalanceError("Cannot refund an order that was not charged")

    return _apply_ledger_entry(
        balances=balances,
        ledger=ledger,
        user_telegram_id=user_telegram_id,
        kind="refund",
        amount=charge.amount,
        reason=reason,
        order_id=order_id,
    )


def _apply_ledger_entry(
    *,
    balances: InMemoryBalanceRepository,
    ledger: InMemoryLedgerRepository,
    user_telegram_id: int,
    kind: str,
    amount: Decimal,
    reason: str,
    order_id: str | None,
) -> LedgerEntry:
    now = datetime.now(UTC)
    current = balances.get(user_telegram_id)
    updated = balances.save(
        Balance(
            user_telegram_id=user_telegram_id,
            available=_money(current.available + amount),
            updated_at=now,
        )
    )
    return ledger.save(
        LedgerEntry(
            id=ledger.next_id(),
            user_telegram_id=user_telegram_id,
            kind=kind,
            amount=_money(abs(amount)),
            balance_after=updated.available,
            reason=reason,
            order_id=order_id,
            created_at=now,
        )
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))
