import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.booking import Booking, BookingState, PaymentMode
from app.models.notification import AdminNotification
from app.models.payment import (
    PaymentRecord,
    PaymentStatus,
    PaymentTransaction,
    PaymentTransactionType,
)
from scripts.clear_bookings import clear_bookings


class ClearBookingsTest(unittest.TestCase):
    def test_apply_removes_payment_transaction_history_with_booking_data(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        test_session = sessionmaker(bind=engine)

        with test_session() as db:
            booking = Booking(
                phone_number="+919999999999",
                state=BookingState.CONFIRMED,
                payment_mode=PaymentMode.PAY_AT_STUDIO,
            )
            db.add(booking)
            db.flush()
            db.add_all(
                [
                    PaymentRecord(
                        booking_id=booking.id,
                        mode=PaymentMode.PAY_AT_STUDIO,
                        amount=1000,
                        status=PaymentStatus.PAID,
                    ),
                    PaymentTransaction(
                        booking_id=booking.id,
                        transaction_type=PaymentTransactionType.PAYMENT,
                        amount=1000,
                        mode=PaymentMode.PAY_AT_STUDIO,
                    ),
                    AdminNotification(booking_id=booking.id),
                ]
            )
            db.commit()

        with (
            patch("scripts.clear_bookings.SessionLocal", test_session),
            patch("scripts.clear_bookings.GoogleCalendarService"),
        ):
            clear_bookings(apply=True)

        with Session(engine) as db:
            for model in (Booking, PaymentRecord, PaymentTransaction, AdminNotification):
                self.assertEqual(db.scalar(select(func.count()).select_from(model)), 0)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
