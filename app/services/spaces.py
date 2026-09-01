import json
from dataclasses import dataclass

from sqlalchemy import delete, select
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
        short_description=(
            "A versatile, character-rich studio designed for portraits, fashion, beauty, baby shoots, "
            "products, reels and creative concepts."
        ),
        brochure=(
            "Cube is a 35 × 17 ft studio designed to give photographers and creators a flexible space "
            "for a wide range of shoots. With a movable backdrop system, natural daylight through a "
            "French door and a distinctive mural wall, Cube combines a clean shooting environment with "
            "its own visual character. Ideal for portraits, fashion, beauty, baby, product, lifestyle "
            "and content shoots."
        ),
        rules=(
            "Please arrive on time and use the studio, equipment, backdrops and props with care.\n"
            "No smoking or wall damage.\n"
            "Keep the space clean and return movable items after use.\n"
            "Any damage or excessive cleaning may attract additional charges."
        ),
        hourly_rate=1000,
        capacity=5,
        dimensions="35 × 17 ft · Approx. 595 sq. ft. · Ideal for small to medium-sized teams",
        equipment=(
            "Movable backdrop system",
            "Studio lighting equipment",
            "Light stands & modifiers",
            "Backdrop support system",
        ),
        amenities=(
            "Natural Daylight French Door",
            "Movable Backdrop System",
            "Changing Corner",
            "Client Seating",
            "Wi-Fi",
            "Signature Mural Wall",
        ),
        cover_image=(
            "https://images.unsplash.com/photo-1615458509633-f15b61bdacb8"
            "?auto=format&fit=crop&w=1400&q=85"
        ),
        max_duration_hours=10.0,
        booking_purposes=(
            "Portrait Shoot",
            "Fashion Shoot",
            "Beauty / Makeup Shoot",
            "Baby Shoot",
            "Family Portraits",
            "Product Shoot",
            "Lifestyle Shoot",
            "Reels & Content Creation",
            "Creative / Conceptual Shoot",
            "Couple / Pre-wedding Shoot",
        ),
    ),
    "2": StudioSpace(
        id="premium_large",
        slug="arena",
        name="Arena",
        short_description=(
            "A spacious, production-ready studio built for larger concepts, fashion, campaigns, "
            "lifestyle shoots, content creation and creative productions."
        ),
        brochure=(
            "Arena is a 45 × 17 ft studio created for creators who need more room to build, move and "
            "experiment. Featuring an approximately 150 sq. ft. cyclorama, lifestyle arch wall, movable "
            "backdrop system, natural daylight through a French door and a Marshall Tufton Bluetooth "
            "speaker, Arena offers the flexibility required for larger shoots and productions while "
            "retaining the character of a creative studio."
        ),
        rules=(
            "Please arrive on time and use the studio, cyclorama, equipment, backdrops and props with care.\n"
            "No smoking or wall damage.\n"
            "The cyclorama must be treated with extra care.\n"
            "Keep the space clean and return movable items after use.\n"
            "Any damage or excessive cleaning may attract additional charges."
        ),
        hourly_rate=1500,
        capacity=10,
        dimensions="45 × 17 ft · Approx. 765 sq. ft. · Ideal for medium to large teams and productions",
        equipment=(
            "Approx. 150 sq. ft. Cyclorama",
            "Movable Backdrop System",
            "Studio Lighting Equipment",
            "Light Stands & Modifiers",
            "Backdrop Support System",
            "Marshall Tufton Bluetooth Speaker",
        ),
        amenities=(
            "Approx. 150 sq. ft. Cyclorama",
            "Lifestyle Arch Wall",
            "Natural Daylight French Door",
            "Movable Backdrop System",
            "Changing Corner",
            "Client Seating",
            "Wi-Fi",
            "Marshall Tufton Bluetooth Speaker",
            "Signature Mural Wall",
        ),
        cover_image=(
            "https://images.unsplash.com/photo-1664817550969-5e76adc4a3fe"
            "?auto=format&fit=crop&w=1400&q=85"
        ),
        max_duration_hours=10.0,
        booking_purposes=(
            "Fashion Shoot",
            "Editorial Shoot",
            "Campaign Shoot",
            "Beauty Shoot",
            "Product Shoot",
            "Lifestyle Shoot",
            "Baby Shoot",
            "Reels & Content Creation",
            "Music / Video Production",
            "Creative / Conceptual Shoot",
            "Couple / Pre-wedding Shoot",
            "Larger Productions",
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


def overwrite_studio_settings_with_defaults(db: Session, commit: bool = True) -> None:
    """Explicitly replace saved studio profiles with the code defaults.

    Normal application startup only seeds missing values. This maintenance helper
    is intentionally separate so an owner must opt in before saved settings are
    overwritten in an existing database.
    """
    seed_studio_settings(db, commit=False)
    rows = {row.id: row for row in db.scalars(select(StudioSetting))}

    for sort_order, space in enumerate(SPACES.values(), start=1):
        row = rows[space.id]
        row.slug = space.slug
        row.sort_order = sort_order
        row.name = space.name
        row.short_description = space.short_description
        row.brochure = space.brochure
        row.rules = space.rules
        row.hourly_rate = space.hourly_rate
        row.capacity = space.capacity
        row.dimensions = space.dimensions
        row.equipment_json = json.dumps(space.equipment)
        row.amenities_json = json.dumps(space.amenities)
        row.cover_image = space.cover_image
        row.opening_time = space.opening_time
        row.closing_time = space.closing_time
        row.min_duration_hours = space.min_duration_hours
        row.max_duration_hours = space.max_duration_hours
        row.is_active = space.is_active

        db.execute(delete(StudioPurposeOption).where(StudioPurposeOption.space_id == space.id))
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

