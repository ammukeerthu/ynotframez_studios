import csv
import json
from math import ceil
from io import StringIO
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.booking_rules import CURRENT_TERMS_VERSION
from app.core.config import settings
from app.core.database import get_db
from app.models.availability import AvailabilityBlock
from app.models.admin import AdminUser
from app.models.booking import Booking, BookingState, PaymentMode
from app.models.notification import AdminNotification
from app.models.payment import (
    PaymentRecord,
    PaymentStatus,
    PaymentTransaction,
    PaymentTransactionType,
)
from app.models.studio import StudioPurposeOption, StudioSetting
from app.schemas.admin import (
    ADMIN_PAYMENT_METHODS_BY_MODE,
    AdminBookingResponse,
    AdminOfflineBookingCreate,
    AdminBookingUpdate,
    AdminAvailabilityBlockCreate,
    AdminAvailabilityBlockResponse,
    AdminAvailabilitySlotResponse,
    AdminDayAvailabilityResponse,
    AdminChangePasswordRequest,
    AdminLoginRequest,
    AdminAlertItem,
    AdminAlertsResponse,
    AdminBookingsOverviewResponse,
    AdminFundsOverviewResponse,
    AdminOverviewResponse,
    AdminUnavailabilityOverviewResponse,
    AdminPaymentUpdate,
    AdminSessionResponse,
    AdminSetupRequest,
    AdminStaffPasswordReset,
    AdminStaffUserCreate,
    AdminStaffUserResponse,
    AdminStudioResponse,
    AdminStudioUpdate,
)
from app.schemas.booking import AvailabilityRequest
from app.services.admin_auth import (
    create_admin_session,
    hash_admin_password,
    read_admin_session,
    verify_admin_password,
)
from app.services.availability_service import interval_for, intervals_overlap, overlapping_block, overlapping_booking
from app.services.booking_service import BookingApplicationService, BookingUnavailableError
from app.services.payment_service import PaymentLifecycleError, PaymentService
from app.services.spaces import get_space_by_id, invalidate_public_space_cache, list_spaces, seed_studio_settings

router = APIRouter(prefix="/api/admin", tags=["Admin"])
SESSION_COOKIE = "ynf_admin_session"
OWNER_ROLE = "owner"
STAFF_ROLE = "staff"
MAX_STAFF_USERS = 2


def require_admin(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> AdminUser:
    user = _session_user(session_token, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin sign-in required.")
    return user


def require_owner(user: AdminUser = Depends(require_admin)) -> AdminUser:
    if user.role != OWNER_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner access is required for this action.",
        )
    return user


@router.post("/setup", response_model=AdminSessionResponse, status_code=status.HTTP_201_CREATED)
def admin_setup(
    payload: AdminSetupRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AdminSessionResponse:
    if db.scalar(select(AdminUser.id).limit(1)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The owner account is already configured.")
    salt, password_hash = hash_admin_password(payload.password)
    user = AdminUser(
        username=payload.username.strip(),
        password_salt=salt,
        password_hash=password_hash,
        role=OWNER_ROLE,
        session_version=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_session_cookie(response, user)
    return AdminSessionResponse(
        authenticated=True,
        username=user.username,
        role=user.role,
        setup_required=False,
    )


@router.post("/login", response_model=AdminSessionResponse)
def admin_login(
    payload: AdminLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AdminSessionResponse:
    user = db.scalar(select(AdminUser).where(AdminUser.username == payload.username.strip()))
    if user is None or not verify_admin_password(payload.password, user.password_salt, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
    _set_session_cookie(response, user)
    return AdminSessionResponse(authenticated=True, username=user.username, role=user.role)


@router.post("/logout", response_model=AdminSessionResponse)
def admin_logout(response: Response) -> AdminSessionResponse:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return AdminSessionResponse(authenticated=False)


@router.get("/session", response_model=AdminSessionResponse)
def admin_session(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> AdminSessionResponse:
    setup_required = db.scalar(select(AdminUser.id).limit(1)) is None
    user = _session_user(session_token, db)
    return AdminSessionResponse(
        authenticated=user is not None,
        username=user.username if user else None,
        role=user.role if user else None,
        setup_required=setup_required,
    )


@router.post("/change-password", response_model=AdminSessionResponse)
def admin_change_password(
    payload: AdminChangePasswordRequest,
    response: Response,
    user: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminSessionResponse:
    if not verify_admin_password(payload.current_password, user.password_salt, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")
    if verify_admin_password(payload.new_password, user.password_salt, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose a different new password.")
    salt, password_hash = hash_admin_password(payload.new_password)
    user.password_salt = salt
    user.password_hash = password_hash
    user.session_version += 1
    db.commit()
    db.refresh(user)
    _set_session_cookie(response, user)
    return AdminSessionResponse(authenticated=True, username=user.username, role=user.role)


@router.get("/staff-users", response_model=list[AdminStaffUserResponse])
def admin_staff_users(
    _owner: AdminUser = Depends(require_owner),
    db: Session = Depends(get_db),
) -> list[AdminStaffUserResponse]:
    users = db.scalars(
        select(AdminUser).where(AdminUser.role == STAFF_ROLE).order_by(AdminUser.created_at, AdminUser.id)
    )
    return [_serialize_staff_user(user) for user in users]


@router.post(
    "/staff-users",
    response_model=AdminStaffUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_staff_user(
    payload: AdminStaffUserCreate,
    _owner: AdminUser = Depends(require_owner),
    db: Session = Depends(get_db),
) -> AdminStaffUserResponse:
    username = payload.username.strip()
    # Serialize staff creation per owner so concurrent requests cannot exceed the two-user limit.
    db.execute(select(AdminUser.id).where(AdminUser.id == _owner.id).with_for_update())
    existing = db.scalar(select(AdminUser).where(func.lower(AdminUser.username) == username.lower()))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That username is already in use.")
    staff_count = db.scalar(
        select(func.count()).select_from(AdminUser).where(AdminUser.role == STAFF_ROLE)
    ) or 0
    if staff_count >= MAX_STAFF_USERS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A maximum of {MAX_STAFF_USERS} staff users is allowed.",
        )
    salt, password_hash = hash_admin_password(payload.password)
    user = AdminUser(
        username=username,
        password_salt=salt,
        password_hash=password_hash,
        role=STAFF_ROLE,
        session_version=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize_staff_user(user)


@router.post("/staff-users/{user_id}/reset-password", response_model=AdminStaffUserResponse)
def admin_reset_staff_password(
    user_id: int,
    payload: AdminStaffPasswordReset,
    _owner: AdminUser = Depends(require_owner),
    db: Session = Depends(get_db),
) -> AdminStaffUserResponse:
    user = db.get(AdminUser, user_id)
    if user is None or user.role != STAFF_ROLE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff user not found.")
    salt, password_hash = hash_admin_password(payload.password)
    user.password_salt = salt
    user.password_hash = password_hash
    user.session_version += 1
    db.commit()
    db.refresh(user)
    return _serialize_staff_user(user)


@router.delete("/staff-users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_staff_user(
    user_id: int,
    _owner: AdminUser = Depends(require_owner),
    db: Session = Depends(get_db),
) -> Response:
    user = db.get(AdminUser, user_id)
    if user is None or user.role != STAFF_ROLE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff user not found.")
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/studios",
    response_model=list[AdminStudioResponse],
    dependencies=[Depends(require_admin)],
)
def admin_studios(db: Session = Depends(get_db)) -> list[AdminStudioResponse]:
    seed_studio_settings(db)
    rows = db.scalars(select(StudioSetting).order_by(StudioSetting.sort_order, StudioSetting.id))
    return [_serialize_studio(row, db) for row in rows]


@router.put(
    "/studios/{space_id}",
    response_model=AdminStudioResponse,
    dependencies=[Depends(require_owner)],
)
def admin_update_studio(
    space_id: str,
    payload: AdminStudioUpdate,
    db: Session = Depends(get_db),
) -> AdminStudioResponse:
    seed_studio_settings(db)
    studio = db.get(StudioSetting, space_id)
    if studio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")

    studio.name = payload.name.strip()
    studio.short_description = payload.short_description.strip()
    studio.brochure = payload.brochure.strip()
    studio.rules = payload.rules.strip()
    studio.hourly_rate = payload.hourly_rate
    studio.capacity = payload.capacity
    studio.dimensions = payload.dimensions.strip()
    studio.equipment_json = json.dumps(payload.equipment)
    studio.amenities_json = json.dumps(payload.amenities)
    studio.cover_image = payload.cover_image.strip()
    studio.opening_time = payload.opening_time.strftime("%H:%M")
    studio.closing_time = payload.closing_time.strftime("%H:%M")
    studio.min_duration_hours = payload.min_duration_hours
    studio.max_duration_hours = payload.max_duration_hours
    studio.is_active = payload.is_active
    db.execute(delete(StudioPurposeOption).where(StudioPurposeOption.space_id == studio.id))
    for sort_order, label in enumerate(payload.booking_purposes, start=1):
        db.add(StudioPurposeOption(space_id=studio.id, label=label, sort_order=sort_order))
    db.commit()
    db.refresh(studio)
    invalidate_public_space_cache()
    return _serialize_studio(studio, db)


def _session_user(token: str | None, db: Session) -> AdminUser | None:
    session = read_admin_session(token)
    if session is None:
        return None
    user = db.scalar(select(AdminUser).where(AdminUser.username == session.username))
    if user is None or user.session_version != session.session_version:
        return None
    return user


def _set_session_cookie(response: Response, user: AdminUser) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_admin_session(user.username, user.session_version),
        max_age=settings.admin_session_hours * 60 * 60,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite="strict",
        path="/",
    )


def _serialize_staff_user(user: AdminUser) -> AdminStaffUserResponse:
    return AdminStaffUserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        created_at=user.created_at.isoformat(),
    )


@router.get("/overview", response_model=AdminOverviewResponse, dependencies=[Depends(require_admin)])
def admin_overview(db: Session = Depends(get_db)) -> AdminOverviewResponse:
    today = datetime.now(ZoneInfo(settings.studio_timezone)).date().isoformat()
    confirmed = list(db.scalars(select(Booking).where(Booking.state == BookingState.CONFIRMED)))
    payment_records = {
        record.booking_id: record
        for record in db.scalars(select(PaymentRecord))
    }
    transaction_totals: dict[int, int] = {}
    refund_totals: dict[int, int] = {}
    for transaction in db.scalars(select(PaymentTransaction)):
        target = (
            transaction_totals
            if transaction.transaction_type == PaymentTransactionType.PAYMENT
            else refund_totals
        )
        target[transaction.booking_id] = target.get(transaction.booking_id, 0) + transaction.amount
    collected_value = 0
    outstanding_value = 0
    for booking in confirmed:
        record = payment_records.get(booking.id)
        amount = record.amount if record else _booking_amount(booking, db)
        payment_status = record.status if record else PaymentStatus.PENDING
        received = max(
            0,
            transaction_totals.get(booking.id, 0) - refund_totals.get(booking.id, 0),
        )
        collected_value += received
        if payment_status in {PaymentStatus.PENDING, PaymentStatus.PARTIALLY_PAID}:
            outstanding_value += max(0, amount - transaction_totals.get(booking.id, 0))
    refund_due_value = sum(
        max(
            0,
            transaction_totals.get(record.booking_id, 0)
            - refund_totals.get(record.booking_id, 0),
        )
        for record in payment_records.values()
        if record.status == PaymentStatus.REFUND_DUE
    )
    return AdminOverviewResponse(
        bookings_today=sum(booking.booking_date == today for booking in confirmed),
        upcoming_bookings=sum(bool(booking.booking_date and booking.booking_date >= today) for booking in confirmed),
        confirmed_bookings=len(confirmed),
        estimated_value=sum(_booking_amount(booking, db) for booking in confirmed),
        collected_value=collected_value,
        outstanding_value=outstanding_value,
        refund_due_value=refund_due_value,
    )


def _month_bounds(month: str | None) -> tuple[date, date, str]:
    selected_month = month or datetime.now(ZoneInfo(settings.studio_timezone)).strftime("%Y-%m")
    try:
        first_day = datetime.strptime(f"{selected_month}-01", "%Y-%m-%d").date()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Month must use YYYY-MM format.",
        ) from error
    next_month = (
        date(first_day.year + 1, 1, 1)
        if first_day.month == 12
        else date(first_day.year, first_day.month + 1, 1)
    )
    return first_day, next_month, selected_month


def _payment_amount_maps(
    db: Session,
) -> tuple[dict[int, PaymentRecord], dict[int, int], dict[int, int]]:
    payment_records = {record.booking_id: record for record in db.scalars(select(PaymentRecord))}
    payment_totals: dict[int, int] = {}
    refund_totals: dict[int, int] = {}
    for transaction in db.scalars(select(PaymentTransaction)):
        target = (
            payment_totals
            if transaction.transaction_type == PaymentTransactionType.PAYMENT
            else refund_totals
        )
        target[transaction.booking_id] = target.get(transaction.booking_id, 0) + transaction.amount
    return payment_records, payment_totals, refund_totals


def _fund_amounts(
    bookings: list[Booking],
    payment_records: dict[int, PaymentRecord],
    payment_totals: dict[int, int],
    refund_totals: dict[int, int],
    db: Session,
) -> tuple[int, int, int]:
    estimated_amount = 0
    collected_amount = 0
    pending_amount = 0
    for booking in bookings:
        record = payment_records.get(booking.id)
        if record and record.status in {PaymentStatus.REFUND_DUE, PaymentStatus.REFUNDED, PaymentStatus.VOID}:
            continue
        amount = record.amount if record else _booking_amount(booking, db)
        received = max(
            0,
            payment_totals.get(booking.id, 0) - refund_totals.get(booking.id, 0),
        )
        estimated_amount += amount
        collected_amount += received
        if record is None or record.status in {PaymentStatus.PENDING, PaymentStatus.PARTIALLY_PAID}:
            pending_amount += max(0, amount - received)
    return estimated_amount, collected_amount, pending_amount


@router.get(
    "/overview/funds",
    response_model=AdminFundsOverviewResponse,
    dependencies=[Depends(require_admin)],
)
def admin_funds_overview(
    month: str | None = None,
    db: Session = Depends(get_db),
    year: int | None = None,
    space_id: str | None = None,
) -> AdminFundsOverviewResponse:
    if year is not None and not 2000 <= year <= 2100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Year must be between 2000 and 2100.")
    if space_id and len(space_id) > 64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Studio space is invalid.")
    if space_id and get_space_by_id(space_id, db, include_inactive=True) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")

    statement = select(Booking).where(Booking.state == BookingState.CONFIRMED)
    if space_id:
        statement = statement.where(Booking.space_id == space_id)
    bookings = list(db.scalars(statement))

    month_first, month_next, chart_month = _month_bounds(month)
    selected_year = year or (month_first.year if month else datetime.now(ZoneInfo(settings.studio_timezone)).year)
    month_bookings = [
        booking
        for booking in bookings
        if booking.booking_date
        and month_first.isoformat() <= booking.booking_date < month_next.isoformat()
    ]
    year_prefix = f"{selected_year:04d}-"
    year_bookings = [
        booking for booking in bookings if booking.booking_date and booking.booking_date.startswith(year_prefix)
    ]
    payment_records, payment_totals, refund_totals = _payment_amount_maps(db)

    summary_amounts = _fund_amounts(bookings, payment_records, payment_totals, refund_totals, db)
    month_amounts = _fund_amounts(month_bookings, payment_records, payment_totals, refund_totals, db)
    legacy_amounts = month_amounts if month else summary_amounts
    yearly_collections = []
    for month_number in range(1, 13):
        month_prefix = f"{selected_year:04d}-{month_number:02d}-"
        month_values = _fund_amounts(
            [
                booking
                for booking in year_bookings
                if booking.booking_date and booking.booking_date.startswith(month_prefix)
            ],
            payment_records,
            payment_totals,
            refund_totals,
            db,
        )
        yearly_collections.append(
            {
                "month": month_number,
                "estimated_amount": month_values[0],
                "collected_amount": month_values[1],
                "pending_amount": month_values[2],
            }
        )

    cashflow_bookings_statement = select(Booking)
    if space_id:
        cashflow_bookings_statement = cashflow_bookings_statement.where(Booking.space_id == space_id)
    cashflow_booking_ids = {booking.id for booking in db.scalars(cashflow_bookings_statement)}
    cashflow_by_month = {
        month_number: {"received": 0, "refunded": 0}
        for month_number in range(1, 13)
    }
    if cashflow_booking_ids:
        transactions = db.scalars(
            select(PaymentTransaction).where(PaymentTransaction.booking_id.in_(cashflow_booking_ids))
        )
        for transaction in transactions:
            occurred_at = transaction.occurred_at
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=UTC)
            local_occurred_at = occurred_at.astimezone(ZoneInfo(settings.studio_timezone))
            if local_occurred_at.year != selected_year:
                continue
            bucket = cashflow_by_month[local_occurred_at.month]
            if transaction.transaction_type == PaymentTransactionType.PAYMENT:
                bucket["received"] += transaction.amount
            else:
                bucket["refunded"] += transaction.amount
    yearly_cashflow = [
        {
            "month": month_number,
            "received_amount": cashflow_by_month[month_number]["received"],
            "refunded_amount": cashflow_by_month[month_number]["refunded"],
            "net_amount": (
                cashflow_by_month[month_number]["received"]
                - cashflow_by_month[month_number]["refunded"]
            ),
        }
        for month_number in range(1, 13)
    ]

    outstanding_bookings = []
    for booking in bookings:
        record = payment_records.get(booking.id)
        if record and record.status not in {PaymentStatus.PENDING, PaymentStatus.PARTIALLY_PAID}:
            continue
        total_amount = record.amount if record else _booking_amount(booking, db)
        amount_paid = max(
            0,
            payment_totals.get(booking.id, 0) - refund_totals.get(booking.id, 0),
        )
        balance_due = max(0, total_amount - amount_paid)
        if not balance_due:
            continue
        booking_date = booking.booking_date or ""
        start_time = booking.start_time or "00:00"
        start_at = datetime.combine(
            date.fromisoformat(booking_date) if booking_date else date.min,
            time.fromisoformat(start_time),
        )
        space = get_space_by_id(booking.space_id, db, include_inactive=True)
        outstanding_bookings.append(
            {
                "id": booking.id,
                "reference": f"YNF-{booking.id:06d}",
                "customer_name": booking.customer_name or "Customer",
                "phone_number": booking.phone_number,
                "space_name": space.name if space else booking.space_id or "Studio",
                "booking_date": booking_date,
                "start_time": start_time,
                "end_time": (start_at + timedelta(hours=booking.duration_hours or 0)).strftime("%H:%M"),
                "total_amount": total_amount,
                "amount_paid": amount_paid,
                "balance_due": balance_due,
                "payment_status": (record.status if record else PaymentStatus.PENDING).value,
            }
        )
    outstanding_bookings.sort(key=lambda item: (item["booking_date"], item["start_time"], item["id"]))

    return AdminFundsOverviewResponse(
        month=chart_month if month else None,
        year=selected_year,
        space_id=space_id,
        estimated_amount=legacy_amounts[0],
        collected_amount=legacy_amounts[1],
        outstanding_amount=legacy_amounts[2],
        summary_estimated_amount=summary_amounts[0],
        summary_collected_amount=summary_amounts[1],
        summary_pending_amount=summary_amounts[2],
        month_estimated_amount=month_amounts[0],
        month_collected_amount=month_amounts[1],
        month_pending_amount=month_amounts[2],
        yearly_collections=yearly_collections,
        yearly_cashflow=yearly_cashflow,
        outstanding_bookings=outstanding_bookings,
    )


@router.get(
    "/overview/bookings",
    response_model=AdminBookingsOverviewResponse,
    dependencies=[Depends(require_admin)],
)
def admin_bookings_overview(
    day_offset: int = Query(default=0, ge=-1, le=1),
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> AdminBookingsOverviewResponse:
    studio_today = datetime.now(ZoneInfo(settings.studio_timezone)).date()
    selected_date = studio_today + timedelta(days=day_offset)
    day_bookings = list(
        db.scalars(
            select(Booking)
            .where(
                Booking.state == BookingState.CONFIRMED,
                Booking.booking_date == selected_date.isoformat(),
            )
            .order_by(Booking.start_time, Booking.id)
        )
    )
    first_day, next_month, selected_month = _month_bounds(month)
    month_bookings = list(
        db.scalars(
            select(Booking).where(
                Booking.state == BookingState.CONFIRMED,
                Booking.booking_date >= first_day.isoformat(),
                Booking.booking_date < next_month.isoformat(),
            )
        )
    )
    booked_hours: dict[str, float] = {}
    for booking in month_bookings:
        if booking.space_id and booking.duration_hours:
            booked_hours[booking.space_id] = booked_hours.get(booking.space_id, 0) + booking.duration_hours

    days_in_month = (next_month - first_day).days
    utilization = []
    for space in list_spaces(db, include_inactive=True):
        opening = datetime.combine(first_day, time.fromisoformat(space.opening_time))
        closing = datetime.combine(first_day, time.fromisoformat(space.closing_time))
        available_hours = max(0.0, (closing - opening).total_seconds() / 3600) * days_in_month
        space_booked_hours = booked_hours.get(space.id, 0.0)
        utilization.append(
            {
                "space_id": space.id,
                "space_name": space.name,
                "booked_hours": round(space_booked_hours, 1),
                "available_hours": round(available_hours, 1),
                "utilization_percent": round(
                    (space_booked_hours / available_hours * 100) if available_hours else 0,
                    1,
                ),
            }
        )

    booking_items = []
    for booking in day_bookings:
        start = time.fromisoformat(booking.start_time or "00:00")
        start_at = datetime.combine(selected_date, start)
        end_time = (start_at + timedelta(hours=booking.duration_hours or 0)).strftime("%H:%M")
        space = get_space_by_id(booking.space_id, db, include_inactive=True)
        booking_items.append(
            {
                "id": booking.id,
                "reference": f"YNF-{booking.id:06d}",
                "space_name": space.name if space else booking.space_id or "Not selected",
                "booking_date": booking.booking_date or selected_date.isoformat(),
                "start_time": booking.start_time or "00:00",
                "end_time": end_time,
                "customer_name": booking.customer_name or "Incomplete booking",
                "phone_number": booking.phone_number,
            }
        )
    return AdminBookingsOverviewResponse(
        selected_date=selected_date.isoformat(),
        total_bookings=len(booking_items),
        bookings=booking_items,
        utilization_month=selected_month,
        studio_utilization=utilization,
    )


@router.get(
    "/overview/unavailability",
    response_model=AdminUnavailabilityOverviewResponse,
    dependencies=[Depends(require_admin)],
)
def admin_unavailability_overview(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    year: int | None = None,
    space_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> AdminUnavailabilityOverviewResponse:
    if year is not None and not 2000 <= year <= 2100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Year must be between 2000 and 2100.")
    if space_id and len(space_id) > 64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Studio space is invalid.")
    if space_id and get_space_by_id(space_id, db, include_inactive=True) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")

    studio_now = datetime.now(ZoneInfo(settings.studio_timezone))
    week_start = studio_now.date() - timedelta(days=studio_now.weekday())
    blocked_from = date_from or week_start
    blocked_to = date_to or (week_start + timedelta(days=6))
    if blocked_from > blocked_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The blocked-time start date must be on or before the end date.",
        )

    first_day, next_month, selected_month = _month_bounds(month)
    selected_year = year or (first_day.year if month else studio_now.year)
    statement = select(AvailabilityBlock)
    if space_id:
        statement = statement.where(AvailabilityBlock.space_id == space_id)
    blocks = list(db.scalars(statement))
    month_blocks = [
        block
        for block in blocks
        if first_day.isoformat() <= block.booking_date < next_month.isoformat()
    ]
    year_prefix = f"{selected_year:04d}-"
    year_blocks = [block for block in blocks if block.booking_date.startswith(year_prefix)]
    upcoming_blocks = []
    for block in blocks:
        block_date = date.fromisoformat(block.booking_date)
        block_start = datetime.combine(
            block_date,
            time.fromisoformat(block.start_time),
            tzinfo=ZoneInfo(settings.studio_timezone),
        )
        if not blocked_from <= block_date <= blocked_to or block_start < studio_now:
            continue
        block_end = block_start + timedelta(hours=block.duration_hours)
        space = get_space_by_id(block.space_id, db, include_inactive=True)
        upcoming_blocks.append(
            {
                "id": block.id,
                "space_id": block.space_id,
                "space_name": space.name if space else block.space_id,
                "booking_date": block.booking_date,
                "start_time": block.start_time,
                "end_time": block_end.strftime("%H:%M"),
                "duration_hours": block.duration_hours,
                "reason": block.reason or "Other",
            }
        )
    upcoming_blocks.sort(key=lambda item: (item["booking_date"], item["start_time"], item["id"]))

    def reason_breakdown(items: list[AvailabilityBlock]) -> list[dict[str, str | float]]:
        reason_hours: dict[str, float] = {}
        for block in items:
            reason = block.reason or "Other"
            reason_hours[reason] = reason_hours.get(reason, 0) + block.duration_hours
        return [
            {"reason": reason, "blocked_hours": round(hours, 1)}
            for reason, hours in sorted(reason_hours.items(), key=lambda item: (-item[1], item[0]))
        ]

    summary_reasons = reason_breakdown(blocks)
    month_reasons = reason_breakdown(month_blocks)
    year_reasons = reason_breakdown(year_blocks)
    yearly_blocked_hours = []
    for month_number in range(1, 13):
        month_prefix = f"{selected_year:04d}-{month_number:02d}-"
        yearly_blocked_hours.append(
            {
                "month": month_number,
                "blocked_hours": round(
                    sum(
                        block.duration_hours
                        for block in year_blocks
                        if block.booking_date.startswith(month_prefix)
                    ),
                    1,
                ),
            }
        )
    month_hours_by_space: dict[str, float] = {}
    for block in month_blocks:
        month_hours_by_space[block.space_id] = (
            month_hours_by_space.get(block.space_id, 0) + block.duration_hours
        )
    month_studio_hours = [
        {
            "space_id": space.id,
            "space_name": space.name,
            "blocked_hours": round(month_hours_by_space.get(space.id, 0), 1),
        }
        for space in list_spaces(db, include_inactive=True)
        if not space_id or space.id == space_id
    ]
    summary_total = round(sum(item["blocked_hours"] for item in summary_reasons), 1)
    month_total = round(sum(item["blocked_hours"] for item in month_reasons), 1)
    year_total = round(sum(item["blocked_hours"] for item in year_reasons), 1)
    return AdminUnavailabilityOverviewResponse(
        month=selected_month,
        year=selected_year,
        space_id=space_id,
        blocked_date_from=blocked_from.isoformat(),
        blocked_date_to=blocked_to.isoformat(),
        upcoming_blocks=upcoming_blocks,
        total_blocked_hours=month_total,
        reasons=month_reasons,
        summary_total_blocked_hours=summary_total,
        month_total_blocked_hours=month_total,
        year_total_blocked_hours=year_total,
        month_reasons=month_reasons,
        year_reasons=year_reasons,
        yearly_blocked_hours=yearly_blocked_hours,
        month_studio_hours=month_studio_hours,
    )


def _booking_window(booking: Booking, timezone: ZoneInfo) -> tuple[datetime, datetime] | None:
    if not booking.booking_date or not booking.start_time or not booking.duration_hours:
        return None
    start = datetime.combine(
        date.fromisoformat(booking.booking_date),
        time.fromisoformat(booking.start_time),
        tzinfo=timezone,
    )
    return start, start + timedelta(hours=booking.duration_hours)


def _operational_alerts(db: Session, now: datetime) -> list[AdminAlertItem]:
    timezone = ZoneInfo(settings.studio_timezone)
    local_now = now.astimezone(timezone) if now.tzinfo else now.replace(tzinfo=timezone)
    relevant_dates = {local_now.date().isoformat(), (local_now.date() + timedelta(days=1)).isoformat()}
    bookings = list(
        db.scalars(
            select(Booking)
            .where(
                Booking.state == BookingState.CONFIRMED,
                Booking.booking_date.in_(relevant_dates),
            )
            .order_by(Booking.booking_date, Booking.start_time, Booking.id)
        )
    )
    windows = {
        booking.id: window
        for booking in bookings
        if (window := _booking_window(booking, timezone)) is not None
    }
    alerts: list[AdminAlertItem] = []
    for booking in bookings:
        window = windows.get(booking.id)
        if window is None:
            continue
        start, end = window
        space = get_space_by_id(booking.space_id, db, include_inactive=True)
        space_name = space.name if space else booking.space_id or "Studio"
        customer_name = booking.customer_name or "Customer"
        reference = f"YNF-{booking.id:06d}"
        end_time = end.strftime("%H:%M")
        seconds_to_start = (start - local_now).total_seconds()
        seconds_to_end = (end - local_now).total_seconds()

        if 0 <= seconds_to_start <= 15 * 60:
            minutes = max(0, ceil(seconds_to_start / 60))
            alerts.append(
                AdminAlertItem(
                    id=f"starts-{booking.id}-{booking.booking_date}-{booking.start_time}",
                    kind="starts_soon",
                    priority="urgent",
                    title=f"{space_name} starts in {minutes} min",
                    message=f"Prepare the studio for {customer_name}. Booking begins at {booking.start_time}.",
                    booking_id=booking.id,
                    reference=reference,
                    space_id=booking.space_id or "",
                    space_name=space_name,
                    booking_date=booking.booking_date,
                    start_time=booking.start_time,
                    end_time=end_time,
                    minutes_remaining=minutes,
                )
            )

        if start <= local_now < end and 0 <= seconds_to_end <= 15 * 60:
            minutes = max(0, ceil(seconds_to_end / 60))
            next_booking = next(
                (
                    candidate
                    for candidate in bookings
                    if candidate.space_id == booking.space_id
                    and candidate.id != booking.id
                    and windows.get(candidate.id)
                    and 0 <= (windows[candidate.id][0] - end).total_seconds() <= 30 * 60
                ),
                None,
            )
            next_note = (
                f" Next: {next_booking.customer_name or 'Customer'} at {next_booking.start_time}."
                if next_booking else ""
            )
            alerts.append(
                AdminAlertItem(
                    id=f"ends-{booking.id}-{booking.booking_date}-{end_time}",
                    kind="ends_soon",
                    priority="warning",
                    title=f"{space_name} ends in {minutes} min",
                    message=f"Begin wrap-up and reset the studio after {customer_name}.{next_note}",
                    booking_id=booking.id,
                    reference=reference,
                    space_id=booking.space_id or "",
                    space_name=space_name,
                    booking_date=booking.booking_date,
                    start_time=booking.start_time,
                    end_time=end_time,
                    minutes_remaining=minutes,
                )
            )
    return alerts


@router.get("/alerts", response_model=AdminAlertsResponse, dependencies=[Depends(require_admin)])
def admin_alerts(db: Session = Depends(get_db)) -> AdminAlertsResponse:
    now = datetime.now(ZoneInfo(settings.studio_timezone))
    rows = db.execute(
        select(AdminNotification, Booking)
        .join(Booking, Booking.id == AdminNotification.booking_id)
        .order_by(AdminNotification.created_at.desc())
        .limit(30)
    ).all()
    new_bookings: list[AdminAlertItem] = []
    for notification, booking in rows:
        window = _booking_window(booking, ZoneInfo(settings.studio_timezone))
        if window is None:
            continue
        start, end = window
        space = get_space_by_id(booking.space_id, db, include_inactive=True)
        space_name = space.name if space else booking.space_id or "Studio"
        is_payment_issue = notification.kind == "payment_issue"
        new_bookings.append(
            AdminAlertItem(
                id=f"{notification.kind.replace('_', '-')}-{notification.id}",
                notification_id=notification.id,
                kind=notification.kind,
                priority="urgent" if is_payment_issue else "new",
                title=(
                    f"Payment needs review · {space_name}"
                    if is_payment_issue
                    else f"New booking · {space_name}"
                ),
                message=(
                    "Payment was captured, but the studio could not be reserved. "
                    "Review this booking and arrange a refund or contact the customer."
                    if is_payment_issue
                    else (
                        f"{booking.customer_name or 'Customer'} booked {booking.booking_date} at "
                        f"{booking.start_time} for {booking.duration_hours:g} hour(s)."
                    )
                ),
                booking_id=booking.id,
                reference=f"YNF-{booking.id:06d}",
                space_id=booking.space_id or "",
                space_name=space_name,
                booking_date=booking.booking_date or "",
                start_time=booking.start_time or "",
                end_time=end.strftime("%H:%M"),
                created_at=f"{notification.created_at.isoformat()}Z",
                is_read=notification.read_at is not None,
            )
        )
    return AdminAlertsResponse(
        unread_count=sum(not alert.is_read for alert in new_bookings),
        new_bookings=new_bookings,
        operational=_operational_alerts(db, now),
        generated_at=now.isoformat(),
    )


@router.post("/alerts/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def admin_read_alert(notification_id: int, db: Session = Depends(get_db)) -> Response:
    notification = db.get(AdminNotification, notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")
    notification.read_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/alerts/read-all", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def admin_read_all_alerts(db: Session = Depends(get_db)) -> Response:
    notifications = list(
        db.scalars(select(AdminNotification).where(AdminNotification.read_at.is_(None)))
    )
    read_at = datetime.now(UTC).replace(tzinfo=None)
    for notification in notifications:
        notification.read_at = read_at
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/bookings", response_model=list[AdminBookingResponse], dependencies=[Depends(require_admin)])
def admin_bookings(
    space_id: str | None = None,
    q: str | None = Query(default=None, max_length=120),
    booking_status: str | None = Query(default=None, alias="status"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AdminBookingResponse]:
    service = BookingApplicationService(db)
    if service.expire_stale_payment_holds():
        db.commit()
    statement = _filtered_booking_statement(space_id, q, booking_status, date_from, date_to)
    statement = statement.order_by(
        Booking.booking_date.desc().nulls_last(),
        Booking.start_time.desc().nulls_last(),
        Booking.id.desc(),
    ).limit(limit)
    return [_serialize_booking(booking, db) for booking in db.scalars(statement)]


@router.post(
    "/bookings/offline",
    response_model=AdminBookingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_owner)],
)
def admin_create_offline_booking(
    payload: AdminOfflineBookingCreate,
    db: Session = Depends(get_db),
) -> AdminBookingResponse:
    space = get_space_by_id(payload.space_id, db, include_inactive=True)
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")
    if not space.min_duration_hours <= payload.duration_hours <= space.max_duration_hours:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Bookings for {space.name} must be between "
                f"{space.min_duration_hours:g} and {space.max_duration_hours:g} hours."
            ),
        )

    selected_purpose = next(
        (
            purpose
            for purpose in space.booking_purposes
            if purpose.casefold() == payload.purpose.strip().casefold()
        ),
        None,
    )
    if selected_purpose is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Please choose a valid booking purpose for this studio.",
        )

    requested_start, requested_end = interval_for(
        payload.booking_date,
        payload.start_time,
        payload.duration_hours,
    )
    business_start = datetime.combine(payload.booking_date, time.fromisoformat(space.opening_time))
    business_end = datetime.combine(payload.booking_date, time.fromisoformat(space.closing_time))
    if requested_start < business_start or requested_end > business_end:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The booking must fit within {space.name}'s {space.opening_time} to {space.closing_time} hours.",
        )

    service = BookingApplicationService(db)
    studio_now = datetime.now(ZoneInfo(settings.studio_timezone)).replace(tzinfo=None)
    calendar_event_id: str | None = None
    booking: Booking | None = None
    try:
        with service.booking_creation_guard(payload.space_id, payload.booking_date):
            if overlapping_booking(
                db,
                payload.space_id,
                payload.booking_date,
                requested_start,
                requested_end,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That studio already has a booking during the selected time.",
                )
            if overlapping_block(
                db,
                payload.space_id,
                payload.booking_date,
                requested_start,
                requested_end,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That studio is blocked during the selected time.",
                )

            booking = Booking(
                phone_number=payload.phone_number.strip(),
                state=BookingState.CONFIRMED,
                space_id=payload.space_id,
                booking_date=payload.booking_date.isoformat(),
                start_time=payload.start_time.strftime("%H:%M"),
                duration_hours=payload.duration_hours,
                customer_name=payload.customer_name.strip(),
                customer_email=str(payload.customer_email),
                purpose=selected_purpose,
                terms_accepted=CURRENT_TERMS_VERSION,
                payment_mode=PaymentMode.PAY_AT_STUDIO,
            )
            if requested_start > studio_now and not service.calendar.is_available(booking, space=space):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That time is unavailable in the studio calendar.",
                )

            db.add(booking)
            db.flush()
            db.add(
                PaymentRecord(
                    booking_id=booking.id,
                    mode=PaymentMode.PAY_AT_STUDIO,
                    amount=payload.total_amount,
                    status=PaymentStatus.PENDING,
                    payment_method=payload.payment_method,
                )
            )
            calendar_event_id = service.calendar.create_event(booking)
            booking.calendar_event_id = calendar_event_id
            db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        if calendar_event_id:
            try:
                service.calendar.delete_event(calendar_event_id, payload.space_id)
            except Exception as cleanup_error:
                print(
                    "Offline booking calendar cleanup failed:",
                    {"event_id": calendar_event_id, "error": f"{type(cleanup_error).__name__}: {cleanup_error}"},
                )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The offline booking could not be created. Please try again.",
        ) from error

    if booking is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Booking creation failed.")
    db.refresh(booking)
    return _serialize_booking(booking, db)


@router.get("/bookings/export.csv", dependencies=[Depends(require_admin)])
def admin_export_bookings(
    space_id: str | None = None,
    q: str | None = Query(default=None, max_length=120),
    booking_status: str | None = Query(default=None, alias="status"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    service = BookingApplicationService(db)
    if service.expire_stale_payment_holds():
        db.commit()
    statement = _filtered_booking_statement(space_id, q, booking_status, date_from, date_to)
    bookings = list(db.scalars(statement.order_by(Booking.booking_date, Booking.start_time)))
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "Booking reference",
            "Booking status",
            "Payment status",
            "Studio",
            "Date",
            "Start time",
            "End time",
            "Duration hours",
            "Customer name",
            "Email",
            "Phone",
            "Purpose",
            "Payment flow",
            "Payment method",
            "Amount INR",
            "Amount paid INR",
            "Balance due INR",
            "Payment reference",
            "Payment history",
            "Created at UTC",
        ]
    )
    for booking in bookings:
        row = _serialize_booking(booking, db)
        writer.writerow(
            [
                row.reference,
                row.status,
                row.payment_status,
                _csv_safe(row.space_name),
                row.booking_date or "",
                row.start_time or "",
                row.end_time or "",
                row.duration_hours or "",
                _csv_safe(row.customer_name),
                _csv_safe(row.customer_email),
                _csv_safe(row.phone_number),
                _csv_safe(row.purpose),
                row.payment_mode or "",
                row.payment_method or "",
                row.total_amount,
                row.amount_paid,
                row.balance_due,
                _csv_safe(row.payment_reference),
                _csv_safe(
                    " | ".join(
                        f"{transaction.provider_reference or 'No reference'} (INR {transaction.amount})"
                        for transaction in row.payment_transactions
                    )
                ),
                row.created_at,
            ]
        )
    filename = f"ynotframez-bookings-{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return Response(
        content=f"\ufeff{output.getvalue()}",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _filtered_booking_statement(
    space_id: str | None,
    q: str | None,
    booking_status: str | None,
    date_from: date | None,
    date_to: date | None,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The start date must be on or before the end date.",
        )
    statement = select(Booking)
    if space_id:
        statement = statement.where(Booking.space_id == space_id)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Booking.customer_name.ilike(pattern),
                Booking.customer_email.ilike(pattern),
                Booking.phone_number.ilike(pattern),
            )
        )
    if booking_status:
        try:
            state = BookingState(booking_status)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown booking status.") from error
        statement = statement.where(Booking.state == state)
    if date_from:
        statement = statement.where(Booking.booking_date >= date_from.isoformat())
    if date_to:
        statement = statement.where(Booking.booking_date <= date_to.isoformat())
    return statement


@router.get(
    "/bookings/{booking_id}",
    response_model=AdminBookingResponse,
    dependencies=[Depends(require_admin)],
)
def admin_booking_detail(
    booking_id: int,
    db: Session = Depends(get_db),
) -> AdminBookingResponse:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
    return _serialize_booking(booking, db)


@router.patch(
    "/bookings/{booking_id}",
    response_model=AdminBookingResponse,
    dependencies=[Depends(require_owner)],
)
def admin_update_booking(
    booking_id: int,
    payload: AdminBookingUpdate,
    db: Session = Depends(get_db),
) -> AdminBookingResponse:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
    if booking.state != BookingState.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only confirmed bookings can be edited.",
        )
    target_space = get_space_by_id(payload.space_id, db)
    if target_space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")
    if (
        payload.customer_name.strip() != (booking.customer_name or "")
        or payload.phone_number.strip() != booking.phone_number
        or payload.purpose.strip() != (booking.purpose or "")
        or payload.duration_hours != booking.duration_hours
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Customer name, phone number, duration, and purpose cannot be changed.",
        )

    new_date = payload.booking_date.isoformat()
    new_time = payload.start_time.strftime("%H:%M")
    schedule_changed = (
        booking.space_id,
        booking.booking_date,
        booking.start_time,
        booking.duration_hours,
    ) != (payload.space_id, new_date, new_time, payload.duration_hours)
    previous_space_id = booking.space_id
    studio_changed = previous_space_id != payload.space_id
    if studio_changed and (previous_space_id, payload.space_id) != ("standard_small", "premium_large"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Studio downgrades are not allowed. Arena bookings must remain in Arena.",
        )
    service = BookingApplicationService(db)
    if schedule_changed:
        available, message = service.check_availability(
            AvailabilityRequest(
                space_id=payload.space_id,
                booking_date=payload.booking_date,
                start_time=payload.start_time,
                duration_hours=payload.duration_hours,
            ),
            exclude_booking_id=booking.id,
            ignore_calendar_event_id=booking.calendar_event_id,
            enforce_customer_date_window=False,
        )
        if not available:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)

    try:
        booking.space_id = payload.space_id
        booking.booking_date = new_date
        booking.start_time = new_time
        booking.customer_email = str(payload.customer_email)
        payment_record = (
            service.payments.sync_pending_amount(booking)
            if studio_changed
            else service.payments.ensure(booking)
        )
        if booking.payment_mode == PaymentMode.PAY_NOW and payment_record.status == PaymentStatus.PENDING:
            service.prepare_online_payment(booking)
            payment_record.mode = booking.payment_mode
        booking.calendar_event_id = service.calendar.update_event(booking, previous_space_id=previous_space_id)
        service.email.send_booking_updated(booking)
        db.commit()
    except PaymentLifecycleError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The booking could not be updated. Its original schedule and payment amount were retained.",
        ) from error
    db.refresh(booking)
    return _serialize_booking(booking, db)

@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=AdminBookingResponse,
    dependencies=[Depends(require_owner)],
)
def admin_cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
) -> AdminBookingResponse:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
    if booking.state != BookingState.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only confirmed bookings can be cancelled.",
        )

    service = BookingApplicationService(db)
    service.payments.handle_cancellation(booking)
    booking.state = BookingState.CANCELLED
    booking.calendar_event_id = service.calendar.decline_event(booking)
    booking.payment_link = None
    service.email.send_booking_cancelled(booking)
    db.commit()
    db.refresh(booking)
    return _serialize_booking(booking, db)


@router.post(
    "/bookings/{booking_id}/payment",
    response_model=AdminBookingResponse,
    dependencies=[Depends(require_owner)],
)
def admin_update_payment(
    booking_id: int,
    payload: AdminPaymentUpdate,
    db: Session = Depends(get_db),
) -> AdminBookingResponse:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
    service = BookingApplicationService(db)
    payments = service.payments
    try:
        if payload.status == PaymentStatus.PAID:
            payment_mode = booking.payment_mode or PaymentMode.PAY_AT_STUDIO
            if payload.payment_method not in ADMIN_PAYMENT_METHODS_BY_MODE[payment_mode.value]:
                raise PaymentLifecycleError(
                    "Choose a payment method available for this booking's payment flow."
                )
            if booking.state == BookingState.PAYMENT_PENDING:
                service.confirm_paid_booking(
                    booking,
                    payload.provider_reference,
                    payment_method=payload.payment_method,
                    amount=payload.amount,
                )
            elif booking.state == BookingState.CONFIRMED:
                payments.mark_paid(
                    booking,
                    payload.provider_reference,
                    payment_method=payload.payment_method,
                    amount=payload.amount,
                )
            else:
                raise PaymentLifecycleError("Only a pending or confirmed booking can be marked as paid.")
        else:
            payments.mark_refunded(booking, payload.provider_reference)
    except (PaymentLifecycleError, BookingUnavailableError, ValueError) as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    db.commit()
    db.refresh(booking)
    return _serialize_booking(booking, db)

@router.get(
    "/availability",
    response_model=AdminDayAvailabilityResponse,
    dependencies=[Depends(require_admin)],
)
def admin_availability(
    space_id: str = Query(...),
    booking_date: date = Query(...),
    db: Session = Depends(get_db),
    exclude_booking_id: int | None = None,
) -> AdminDayAvailabilityResponse:
    space = get_space_by_id(space_id, db, include_inactive=True)
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")

    editing_booking = db.get(Booking, exclude_booking_id) if exclude_booking_id is not None else None
    if exclude_booking_id is not None and editing_booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
    day = BookingApplicationService(db).get_day_availability(
        space_id,
        booking_date,
        exclude_booking_id=exclude_booking_id,
        ignore_calendar_event_id=editing_booking.calendar_event_id if editing_booking else None,
    )
    bookings = list(
        db.scalars(
            select(Booking).where(
                Booking.space_id == space_id,
                Booking.booking_date == booking_date.isoformat(),
                Booking.state.in_([BookingState.CONFIRMED, BookingState.PAYMENT_PENDING]),
            )
        )
    )
    hold_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        minutes=settings.razorpay_payment_hold_minutes
    )
    bookings = [
        booking
        for booking in bookings
        if booking.id != exclude_booking_id
        and (booking.state == BookingState.CONFIRMED or booking.updated_at >= hold_cutoff)
    ]
    blocks = list(
        db.scalars(
            select(AvailabilityBlock).where(
                AvailabilityBlock.space_id == space_id,
                AvailabilityBlock.booking_date == booking_date.isoformat(),
            )
        )
    )

    slots: list[AdminAvailabilitySlotResponse] = []
    for base_slot in day.slots:
        slot_start = datetime.combine(booking_date, time.fromisoformat(base_slot.start_time))
        slot_end = datetime.combine(booking_date, time.fromisoformat(base_slot.end_time))
        booking = _booking_overlapping_slot(bookings, booking_date, slot_start, slot_end)
        block = _block_overlapping_slot(blocks, booking_date, slot_start, slot_end)
        slots.append(
            AdminAvailabilitySlotResponse(
                start_time=base_slot.start_time,
                end_time=base_slot.end_time,
                status="booked" if booking else "blocked" if block else base_slot.status,
                booking_id=booking.id if booking else None,
                booking_reference=f"YNF-{booking.id:06d}" if booking else None,
                customer_name=booking.customer_name if booking else None,
                block_id=block.id if block else None,
                reason=block.reason if block else None,
            )
        )

    return AdminDayAvailabilityResponse(
        space_id=space.id,
        space_name=space.name,
        booking_date=booking_date.isoformat(),
        opening_time=day.opening_time,
        closing_time=day.closing_time,
        slots=slots,
    )


@router.post(
    "/availability/blocks",
    response_model=AdminAvailabilityBlockResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_availability_block(
    payload: AdminAvailabilityBlockCreate,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(require_admin),
) -> AdminAvailabilityBlockResponse:
    space = get_space_by_id(payload.space_id, db, include_inactive=True)
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")

    requested_start, requested_end = interval_for(
        payload.booking_date,
        payload.start_time,
        payload.duration_hours,
    )
    business_start = datetime.combine(payload.booking_date, time.fromisoformat(space.opening_time))
    business_end = datetime.combine(payload.booking_date, time.fromisoformat(space.closing_time))
    studio_now = datetime.now(ZoneInfo(settings.studio_timezone)).replace(tzinfo=None)
    if requested_start <= studio_now and user.role != OWNER_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can record past studio blocks.",
        )
    if requested_start < business_start or requested_end > business_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Blocks must be within studio hours ({business_start:%H:%M} to {business_end:%H:%M}).",
        )
    service = BookingApplicationService(db)
    with service.booking_creation_guard(payload.space_id, payload.booking_date):
        if overlapping_booking(
            db,
            payload.space_id,
            payload.booking_date,
            requested_start,
            requested_end,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A booking or active payment hold already occupies part of that time.",
            )
        if overlapping_block(
            db,
            payload.space_id,
            payload.booking_date,
            requested_start,
            requested_end,
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That time is already blocked.")

        block = AvailabilityBlock(
            space_id=payload.space_id,
            booking_date=payload.booking_date.isoformat(),
            start_time=payload.start_time.strftime("%H:%M"),
            duration_hours=payload.duration_hours,
            reason=payload.reason.strip() or "Owner blocked",
        )
        created_event_id: str | None = None
        try:
            db.add(block)
            db.flush()
            created_event_id = service.calendar.create_availability_block_event(block)
            block.calendar_event_id = created_event_id
            db.commit()
        except Exception as error:
            db.rollback()
            if created_event_id:
                try:
                    service.calendar.delete_event(created_event_id, payload.space_id)
                except Exception as cleanup_error:
                    print(
                        "Availability block calendar cleanup failed:",
                        {"event_id": created_event_id, "error": str(cleanup_error)},
                    )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The studio block could not be added to Google Calendar, so it was not saved.",
            ) from error
        db.refresh(block)
    return _serialize_availability_block(block)


@router.delete(
    "/availability/blocks/{block_id}/slot",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def admin_delete_availability_block_slot(
    block_id: int,
    start_time: time = Query(...),
    db: Session = Depends(get_db),
) -> Response:
    if start_time.minute not in {0, 30} or start_time.second or start_time.microsecond:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start time must be on the hour or half hour.",
        )

    block = db.get(AvailabilityBlock, block_id)
    if block is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability block not found.")

    booking_date = date.fromisoformat(block.booking_date)
    service = BookingApplicationService(db)
    with service.booking_creation_guard(block.space_id, booking_date):
        block = db.get(AvailabilityBlock, block_id)
        if block is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability block not found.")

        block_start, block_end = interval_for(
            booking_date,
            time.fromisoformat(block.start_time),
            block.duration_hours,
        )
        slot_start = datetime.combine(booking_date, start_time)
        slot_end = slot_start + timedelta(minutes=30)
        if slot_start < block_start or slot_end > block_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That half-hour does not belong to this availability block.",
            )

        left_hours = (slot_start - block_start).total_seconds() / 3600
        right_hours = (block_end - slot_end).total_seconds() / 3600
        created_event_ids: list[str] = []
        deleted_event = False
        original_event_id = block.calendar_event_id
        try:
            if left_hours == 0 and right_hours == 0:
                service.calendar.delete_availability_block_event(block)
                deleted_event = bool(block.calendar_event_id)
                db.delete(block)
            elif left_hours == 0:
                block.start_time = slot_end.strftime("%H:%M")
                block.duration_hours = right_hours
                updated_event_id = service.calendar.update_availability_block_event(block)
                if updated_event_id != original_event_id:
                    created_event_ids.append(updated_event_id)
                block.calendar_event_id = updated_event_id
            elif right_hours == 0:
                block.duration_hours = left_hours
                updated_event_id = service.calendar.update_availability_block_event(block)
                if updated_event_id != original_event_id:
                    created_event_ids.append(updated_event_id)
                block.calendar_event_id = updated_event_id
            else:
                block.duration_hours = left_hours
                right_block = AvailabilityBlock(
                    space_id=block.space_id,
                    booking_date=block.booking_date,
                    start_time=slot_end.strftime("%H:%M"),
                    duration_hours=right_hours,
                    reason=block.reason,
                )
                db.add(right_block)
                db.flush()
                right_event_id = service.calendar.create_availability_block_event(right_block)
                created_event_ids.append(right_event_id)
                right_block.calendar_event_id = right_event_id
                updated_event_id = service.calendar.update_availability_block_event(block)
                if updated_event_id != original_event_id:
                    created_event_ids.append(updated_event_id)
                block.calendar_event_id = updated_event_id
            db.commit()
        except Exception as error:
            db.rollback()
            for event_id in created_event_ids:
                try:
                    service.calendar.delete_event(event_id, block.space_id)
                except Exception as cleanup_error:
                    print(
                        "Availability block split cleanup failed:",
                        {"event_id": event_id, "error": str(cleanup_error)},
                    )
            if deleted_event:
                restored = db.get(AvailabilityBlock, block_id)
                if restored is not None:
                    try:
                        restored.calendar_event_id = service.calendar.create_availability_block_event(restored)
                        db.commit()
                    except Exception as restore_error:
                        db.rollback()
                        print(
                            "Availability block calendar restore failed:",
                            {"block_id": block_id, "error": str(restore_error)},
                        )
            elif original_event_id and not original_event_id.startswith("gcal_stub_"):
                restored = db.get(AvailabilityBlock, block_id)
                if restored is not None:
                    try:
                        service.calendar.update_availability_block_event(restored)
                    except Exception as restore_error:
                        print(
                            "Availability block calendar restore failed:",
                            {"block_id": block_id, "error": str(restore_error)},
                        )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The studio block could not be updated in Google Calendar.",
            ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/availability/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def admin_delete_availability_block(
    block_id: int,
    db: Session = Depends(get_db),
) -> Response:
    block = db.get(AvailabilityBlock, block_id)
    if block is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability block not found.")
    service = BookingApplicationService(db)
    deleted_event = bool(block.calendar_event_id)
    try:
        service.calendar.delete_availability_block_event(block)
        db.delete(block)
        db.commit()
    except Exception as error:
        db.rollback()
        if deleted_event:
            restored = db.get(AvailabilityBlock, block_id)
            if restored is not None:
                try:
                    restored.calendar_event_id = service.calendar.create_availability_block_event(restored)
                    db.commit()
                except Exception as restore_error:
                    db.rollback()
                    print(
                        "Availability block calendar restore failed:",
                        {"block_id": block_id, "error": str(restore_error)},
                    )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The studio block could not be removed from Google Calendar.",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _serialize_booking(booking: Booking, db: Session) -> AdminBookingResponse:
    end_time = None
    if booking.booking_date and booking.start_time and booking.duration_hours:
        start = datetime.strptime(f"{booking.booking_date} {booking.start_time}", "%Y-%m-%d %H:%M")
        end_time = (start + timedelta(hours=booking.duration_hours)).strftime("%H:%M")
    space = get_space_by_id(booking.space_id, db, include_inactive=True)
    payment_service = PaymentService(db)
    payment = payment_service.get(booking.id)
    transactions = payment_service.transactions(booking.id)
    inferred_payment_status = (
        PaymentStatus.VOID
        if booking.state in {BookingState.CANCELLED, BookingState.EXPIRED}
        else PaymentStatus.PENDING
    )
    total_amount = payment.amount if payment else _booking_amount(booking, db)
    amount_paid = payment_service.net_received(booking.id) if payment else 0
    balance_due = (
        max(0, total_amount - payment_service.payment_total(booking.id))
        if booking.state == BookingState.CONFIRMED
        and (payment is None or payment.status not in {PaymentStatus.REFUND_DUE, PaymentStatus.REFUNDED, PaymentStatus.VOID})
        else 0
    )
    return AdminBookingResponse(
        id=booking.id,
        reference=f"YNF-{booking.id:06d}",
        status=booking.state.value,
        space_id=booking.space_id,
        space_name=space.name if space else booking.space_id or "Not selected",
        booking_date=booking.booking_date,
        start_time=booking.start_time,
        end_time=end_time,
        duration_hours=booking.duration_hours,
        customer_name=booking.customer_name,
        customer_email=booking.customer_email,
        phone_number=booking.phone_number,
        purpose=booking.purpose,
        terms_accepted=booking.terms_accepted,
        payment_mode=booking.payment_mode.value if booking.payment_mode else None,
        payment_method=payment.payment_method if payment else None,
        payment_status=(payment.status if payment else inferred_payment_status).value,
        payment_reference=payment.provider_reference if payment else None,
        total_amount=total_amount,
        amount_paid=amount_paid,
        balance_due=balance_due,
        payment_transactions=[
            {
                "id": transaction.id,
                "transaction_type": transaction.transaction_type.value,
                "amount": transaction.amount,
                "payment_mode": transaction.mode.value,
                "payment_method": transaction.payment_method,
                "provider_reference": transaction.provider_reference,
                "occurred_at": transaction.occurred_at.isoformat(),
            }
            for transaction in transactions
        ],
        created_at=booking.created_at.isoformat(),
    )


def _serialize_availability_block(block: AvailabilityBlock) -> AdminAvailabilityBlockResponse:
    start = datetime.strptime(f"{block.booking_date} {block.start_time}", "%Y-%m-%d %H:%M")
    return AdminAvailabilityBlockResponse(
        id=block.id,
        space_id=block.space_id,
        booking_date=block.booking_date,
        start_time=block.start_time,
        end_time=(start + timedelta(hours=block.duration_hours)).strftime("%H:%M"),
        duration_hours=block.duration_hours,
        reason=block.reason,
    )


def _booking_overlapping_slot(
    bookings: list[Booking],
    booking_date: date,
    slot_start: datetime,
    slot_end: datetime,
) -> Booking | None:
    for booking in bookings:
        if not booking.start_time or not booking.duration_hours:
            continue
        booking_start, booking_end = interval_for(
            booking_date,
            time.fromisoformat(booking.start_time),
            booking.duration_hours,
        )
        if intervals_overlap(slot_start, slot_end, booking_start, booking_end):
            return booking
    return None


def _block_overlapping_slot(
    blocks: list[AvailabilityBlock],
    booking_date: date,
    slot_start: datetime,
    slot_end: datetime,
) -> AvailabilityBlock | None:
    for block in blocks:
        block_start, block_end = interval_for(
            booking_date,
            time.fromisoformat(block.start_time),
            block.duration_hours,
        )
        if intervals_overlap(slot_start, slot_end, block_start, block_end):
            return block
    return None


def _booking_amount(booking: Booking, db: Session | None = None) -> int:
    space = get_space_by_id(booking.space_id, db, include_inactive=True)
    return int(round((space.hourly_rate if space else 0) * (booking.duration_hours or 0)))


def _serialize_studio(studio: StudioSetting, db: Session) -> AdminStudioResponse:
    def items(value: str) -> list[str]:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        return [str(item) for item in parsed]

    return AdminStudioResponse(
        id=studio.id,
        slug=studio.slug,
        name=studio.name,
        short_description=studio.short_description,
        brochure=studio.brochure,
        rules=studio.rules,
        hourly_rate=studio.hourly_rate,
        capacity=studio.capacity,
        dimensions=studio.dimensions,
        equipment=items(studio.equipment_json),
        amenities=items(studio.amenities_json),
        cover_image=studio.cover_image,
        opening_time=studio.opening_time,
        closing_time=studio.closing_time,
        min_duration_hours=studio.min_duration_hours,
        max_duration_hours=studio.max_duration_hours,
        is_active=studio.is_active,
        booking_purposes=list(
            db.scalars(
                select(StudioPurposeOption.label)
                .where(StudioPurposeOption.space_id == studio.id)
                .order_by(StudioPurposeOption.sort_order, StudioPurposeOption.id)
            )
        ),
    )


def _csv_safe(value: object | None) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text
