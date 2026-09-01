import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.booking_rules import MINIMUM_BOOKING_DURATION_HOURS
from app.models.studio import StudioPurposeOption, StudioSetting


DEFAULT_BOOKING_PURPOSES = (
    "Fashion Shoot",
    "Baby Shoot",
    "Family Portraits",
    "Maternity Shoot",
    "Editorial",
    "E-commerce",
    "Fine Art",
    "Workshop",
)


@dataclass(frozen=True)
class StudioSpace:
    id: str
    slug: str
    name: str
    short_description: str
    brochure: str
    rules: str
    hourly_rate: int
    capacity: int
    dimensions: str
    equipment: tuple[str, ...]
    amenities: tuple[str, ...]
    cover_image: str
    opening_time: str = "09:00"
    closing_time: str = "20:00"
    min_duration_hours: float = MINIMUM_BOOKING_DURATION_HOURS
    max_duration_hours: float = 12.0
    is_active: bool = True
    booking_purposes: tuple[str, ...] = DEFAULT_BOOKING_PURPOSES


SPACES = {
    "1": StudioSpace(
        id="standard_small",
        slug="cube",
        name="Cube",
        short_description="A compact, thoughtfully equipped studio for portraits, products, reels, and interviews.",
        brochure=(
            "Cube: compact studio for portraits, reels, product shoots, and small teams. "
            "Includes basic lights, backdrop support, changing corner, and seating for 4."
        ),
        rules=(
            "Rules: arrive on time, no smoking, no wall damage, clean up props, keep music moderate, "
            "and overtime is charged hourly if available."
        ),
        hourly_rate=1200,
        capacity=4,
        dimensions="Compact studio · seating for 4",
        equipment=("Basic lighting kit", "Backdrop support"),
        amenities=("Changing corner", "Wi-Fi", "Client seating"),
        cover_image=(
            "https://images.unsplash.com/photo-1615458509633-f15b61bdacb8"
            "?auto=format&fit=crop&w=1400&q=85"
        ),
    ),
    "2": StudioSpace(
        id="premium_large",
        slug="arena",
        name="Arena",
        short_description="A spacious production studio for fashion, campaigns, maternity, video, and larger teams.",
        brochure=(
            "Arena: larger studio for fashion, maternity, campaigns, videos, and bigger teams. "
            "Includes premium lighting setup, multiple backdrops, makeup area, lounge seating, and space for 10."
        ),
        rules=(
            "Rules: prior approval needed for heavy props, confetti, smoke, pets, or food setups. "
            "No drilling, painting, unsafe electricals, or unmanaged crowding."
        ),
        hourly_rate=2500,
        capacity=10,
        dimensions="Large studio · seating for 10",
        equipment=("Premium lighting setup", "Multiple backdrops"),
        amenities=("Makeup area", "Lounge seating", "Wi-Fi"),
        cover_image=(
            "https://images.unsplash.com/photo-1664817550969-5e76adc4a3fe"
            "?auto=format&fit=crop&w=1400&q=85"
        ),
    ),
}

LEGACY_SPACE_NAMES = {
    "standard_small": ("Standard Small Space", "Standard Space", "Standard Studio"),
    "premium_large": ("Premium Large Space", "Premium Space", "Premium Studio"),
}
LEGACY_SPACE_SLUGS = {
    "standard-small-space": "cube",
    "standard-space": "cube",
    "standard-studio": "cube",
    "premium-large-space": "arena",
    "premium-space": "arena",
    "premium-studio": "arena",
}


def seed_studio_settings(db: Session, commit: bool = True) -> None:
    existing = {row.id: row for row in db.scalars(select(StudioSetting))}
    purpose_space_ids = set(db.scalars(select(StudioPurposeOption.space_id).distinct()))
    for sort_order, space in enumerate(SPACES.values(), start=1):
        if space.id in existing:
            row = existing[space.id]
            if row.min_duration_hours < MINIMUM_BOOKING_DURATION_HOURS:
                row.min_duration_hours = MINIMUM_BOOKING_DURATION_HOURS
            if row.max_duration_hours < MINIMUM_BOOKING_DURATION_HOURS:
                row.max_duration_hours = MINIMUM_BOOKING_DURATION_HOURS
            legacy_names = LEGACY_SPACE_NAMES.get(space.id, ())
            if row.name in legacy_names:
                row.name = space.name
            if row.slug in LEGACY_SPACE_SLUGS:
                row.slug = LEGACY_SPACE_SLUGS[row.slug]
            for legacy_name in legacy_names:
                if row.brochure.startswith(f"{legacy_name}:"):
                    row.brochure = row.brochure.replace(legacy_name, space.name, 1)
                    break
            if (
                _json_items(row.equipment_json) == space.equipment
                and _json_items(row.amenities_json) == space.equipment + space.amenities
            ):
                row.amenities_json = json.dumps(space.amenities)
        else:
            db.add(
                StudioSetting(
                    id=space.id,
                    slug=space.slug,
                    sort_order=sort_order,
                    name=space.name,
                    short_description=space.short_description,
                    brochure=space.brochure,
                    rules=space.rules,
                    hourly_rate=space.hourly_rate,
                    capacity=space.capacity,
                    dimensions=space.dimensions,
                    equipment_json=json.dumps(space.equipment),
                    amenities_json=json.dumps(space.amenities),
                    cover_image=space.cover_image,
                    opening_time=space.opening_time,
                    closing_time=space.closing_time,
                    min_duration_hours=space.min_duration_hours,
                    max_duration_hours=space.max_duration_hours,
                    is_active=space.is_active,
                )
            )

    # Purpose options reference studio_settings. Flush the parent rows first
    # because these models intentionally do not maintain ORM relationships;
    # PostgreSQL enforces the foreign key while SQLite commonly does not.
    db.flush()

    for space in SPACES.values():
        if space.id not in purpose_space_ids:
            for purpose_order, label in enumerate(space.booking_purposes, start=1):
                db.add(StudioPurposeOption(space_id=space.id, label=label, sort_order=purpose_order))
    if commit:
        db.commit()
    else:
        db.flush()


def list_spaces(db: Session | None = None, include_inactive: bool = False) -> list[StudioSpace]:
    if db is None:
        spaces = list(SPACES.values())
    else:
        statement = select(StudioSetting).order_by(StudioSetting.sort_order, StudioSetting.id)
        rows = list(db.scalars(statement))
        spaces = [_space_from_row(row, db) for row in rows] if rows else list(SPACES.values())
    return spaces if include_inactive else [space for space in spaces if space.is_active]


def list_spaces_message(db: Session | None = None) -> str:
    spaces = list_spaces(db)
    if not spaces:
        return "No studio spaces are accepting new bookings right now. Please contact the studio team."
    choices = "\n".join(f"{index}. {space.name}" for index, space in enumerate(spaces, start=1))
    return (
        "Welcome to our studio booking assistant.\n\n"
        f"Please select a space:\n{choices}\n\n"
        f"Reply with a number from 1 to {len(spaces)}."
    )


def get_space_by_input(value: str, db: Session | None = None) -> StudioSpace | None:
    normalized = value.strip().lower()
    spaces = list_spaces(db)
    if normalized.isdigit():
        index = int(normalized) - 1
        if 0 <= index < len(spaces):
            return spaces[index]
    for space in spaces:
        if normalized in {space.id, space.name.lower()}:
            return space
    return None


def get_space_by_id(
    space_id: str | None,
    db: Session | None = None,
    include_inactive: bool = False,
) -> StudioSpace | None:
    if not space_id:
        return None
    return next(
        (space for space in list_spaces(db, include_inactive=include_inactive) if space.id == space_id),
        None,
    )


def get_space_by_slug(slug: str, db: Session | None = None) -> StudioSpace | None:
    normalized = slug.strip().lower()
    normalized = LEGACY_SPACE_SLUGS.get(normalized, normalized)
    return next((space for space in list_spaces(db) if space.slug == normalized), None)


def _space_from_row(row: StudioSetting, db: Session) -> StudioSpace:
    purposes = tuple(
        db.scalars(
            select(StudioPurposeOption.label)
            .where(StudioPurposeOption.space_id == row.id)
            .order_by(StudioPurposeOption.sort_order, StudioPurposeOption.id)
        )
    )
    return StudioSpace(
        id=row.id,
        slug=row.slug,
        name=row.name,
        short_description=row.short_description,
        brochure=row.brochure,
        rules=row.rules,
        hourly_rate=row.hourly_rate,
        capacity=row.capacity,
        dimensions=row.dimensions,
        equipment=_json_items(row.equipment_json),
        amenities=_json_items(row.amenities_json),
        cover_image=row.cover_image,
        opening_time=row.opening_time,
        closing_time=row.closing_time,
        min_duration_hours=row.min_duration_hours,
        max_duration_hours=row.max_duration_hours,
        is_active=row.is_active,
        booking_purposes=purposes or DEFAULT_BOOKING_PURPOSES,
    )


def _json_items(value: str) -> tuple[str, ...]:
    try:
        items = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ()
    return tuple(str(item).strip() for item in items if str(item).strip())

