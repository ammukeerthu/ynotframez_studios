import csv
import json
from math import ceil
from io import StringIO
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.availability import AvailabilityBlock
from app.models.admin import AdminUser
from app.models.booking import Booking, BookingState, PaymentMode
from app.models.notification import AdminNotification
from app.models.payment import PaymentRecord, PaymentStatus
from app.models.studio import StudioPurposeOption, StudioSetting
from app.schemas.admin import (
    AdminBookingResponse,
    AdminBookingUpdate,
    AdminAvailabilityBlockCreate,
    AdminAvailabilityBlockResponse,
    AdminAvailabilitySlotResponse,
    AdminDayAvailabilityResponse,
    AdminChangePasswordRequest,
    AdminLoginRequest,
    AdminAlertItem,
    AdminAlertsResponse,
    AdminOverviewResponse,
    AdminPaymentUpdate,
    AdminSessionResponse,
    AdminSetupRequest,
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
from app.services.spaces import get_space_by_id, invalidate_public_space_cache, seed_studio_settings

router = APIRouter(prefix="/api/admin", tags=["Admin"])
SESSION_COOKIE = "ynf_admin_session"


def require_admin(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> AdminUser:
    user = _session_user(session_token, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin sign-in required.")
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
        session_version=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_session_cookie(response, user)
    return AdminSessionResponse(authenticated=True, username=user.username, setup_required=False)


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
    return AdminSessionResponse(authenticated=True, username=user.username)


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
    return AdminSessionResponse(authenticated=True, username=user.username)


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
    dependencies=[Depends(require_admin)],
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


@router.get("/overview", response_model=AdminOverviewResponse, dependencies=[Depends(require_admin)])
def admin_overview(db: Session = Depends(get_db)) -> AdminOverviewResponse:
    today = datetime.now(ZoneInfo(settings.studio_timezone)).date().isoformat()
    confirmed = list(db.scalars(select(Booking).where(Booking.state == BookingState.CONFIRMED)))
    payment_records = {
        record.booking_id: record
        for record in db.scalars(select(PaymentRecord))
    }
    collected_value = 0
    outstanding_value = 0
    for booking in confirmed:
        record = payment_records.get(booking.id)
        amount = record.amount if record else _booking_amount(booking, db)
        payment_status = record.status if record else PaymentStatus.PENDING
        if payment_status in {PaymentStatus.PAID, PaymentStatus.REFUND_DUE}:
            collected_value += amount
        elif payment_status == PaymentStatus.PENDING:
            outstanding_value += amount
    refund_due_value = sum(
        record.amount for record in payment_records.values() if record.status == PaymentStatus.REFUND_DUE
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
    statement = statement.order_by(Booking.created_at.desc()).limit(limit)
    return [_serialize_booking(booking, db) for booking in db.scalars(statement)]


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
            "Payment mode",
            "Amount INR",
            "Payment reference",
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
                row.total_amount,
                _csv_safe(row.payment_reference),
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


@router.patch(
    "/bookings/{booking_id}",
    response_model=AdminBookingResponse,
    dependencies=[Depends(require_admin)],
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
    if get_space_by_id(payload.space_id, db) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")

    new_date = payload.booking_date.isoformat()
    new_time = payload.start_time.strftime("%H:%M")
    schedule_changed = (
        booking.space_id,
        booking.booking_date,
        booking.start_time,
        booking.duration_hours,
    ) != (payload.space_id, new_date, new_time, payload.duration_hours)
    previous_space_id = booking.space_id
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
        )
        if not available:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)

    booking.space_id = payload.space_id
    booking.booking_date = new_date
    booking.start_time = new_time
    booking.duration_hours = payload.duration_hours
    booking.customer_name = payload.customer_name.strip()
    booking.customer_email = str(payload.customer_email)
    booking.phone_number = payload.phone_number.strip()
    booking.purpose = payload.purpose.strip()
    try:
        payment_record = service.payments.sync_pending_amount(booking)
    except PaymentLifecycleError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if booking.payment_mode == PaymentMode.PAY_NOW and payment_record.status == PaymentStatus.PENDING:
        service.prepare_online_payment(booking)
        payment_record.mode = booking.payment_mode
    booking.calendar_event_id = service.calendar.update_event(booking, previous_space_id=previous_space_id)
    service.email.send_booking_updated(booking)
    db.commit()
    db.refresh(booking)
    return _serialize_booking(booking, db)


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=AdminBookingResponse,
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
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
            if booking.state == BookingState.PAYMENT_PENDING:
                service.confirm_paid_booking(booking, payload.provider_reference)
            elif booking.state == BookingState.CONFIRMED:
                payments.mark_paid(booking, payload.provider_reference)
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
) -> AdminDayAvailabilityResponse:
    space = get_space_by_id(space_id, db, include_inactive=True)
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")

    day = BookingApplicationService(db).get_day_availability(space_id, booking_date)
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
        if booking.state == BookingState.CONFIRMED or booking.updated_at >= hold_cutoff
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
    dependencies=[Depends(require_admin)],
)
def admin_create_availability_block(
    payload: AdminAvailabilityBlockCreate,
    db: Session = Depends(get_db),
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
    if requested_start <= studio_now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only future studio time can be blocked.")
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
        db.add(block)
        db.commit()
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
        if left_hours == 0 and right_hours == 0:
            db.delete(block)
        elif left_hours == 0:
            block.start_time = slot_end.strftime("%H:%M")
            block.duration_hours = right_hours
        elif right_hours == 0:
            block.duration_hours = left_hours
        else:
            block.duration_hours = left_hours
            db.add(
                AvailabilityBlock(
                    space_id=block.space_id,
                    booking_date=block.booking_date,
                    start_time=slot_end.strftime("%H:%M"),
                    duration_hours=right_hours,
                    reason=block.reason,
                )
            )
        db.commit()
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
    db.delete(block)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _serialize_booking(booking: Booking, db: Session) -> AdminBookingResponse:
    end_time = None
    if booking.booking_date and booking.start_time and booking.duration_hours:
        start = datetime.strptime(f"{booking.booking_date} {booking.start_time}", "%Y-%m-%d %H:%M")
        end_time = (start + timedelta(hours=booking.duration_hours)).strftime("%H:%M")
    space = get_space_by_id(booking.space_id, db, include_inactive=True)
    payment = PaymentService(db).get(booking.id)
    inferred_payment_status = (
        PaymentStatus.VOID
        if booking.state in {BookingState.CANCELLED, BookingState.EXPIRED}
        else PaymentStatus.PENDING
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
        payment_status=(payment.status if payment else inferred_payment_status).value,
        payment_reference=payment.provider_reference if payment else None,
        total_amount=_booking_amount(booking, db),
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
