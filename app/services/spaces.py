import json
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from sqlalchemy import delete, select, text
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
    "Fine Arts",
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
    hero_image: str
    gallery_images: tuple[str, ...]
    opening_time: str = "09:00"
    closing_time: str = "21:00"
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
        cover_image="/static/studio/cube-lifestyle.jpeg",
        hero_image="/static/studio/cube-wide.jpeg",
        gallery_images=("/static/studio/cube-lifestyle.jpeg",),
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
            "Fine Arts",
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
        capacity=8,
        dimensions="45 × 17 ft · Approx. 765 sq. ft. · Ideal for medium to large teams and productions",
        equipment=(
            "Cyclorama",
            "Movable Backdrop System",
            "Studio Lighting Equipment",
            "Light Stands & Modifiers",
            "Backdrop Support System",
            "Marshall Tufton Bluetooth Speaker",
        ),
        amenities=(
            "Cyclorama",
            "Lifestyle Arch Wall",
            "Natural Daylight French Door",
            "Movable Backdrop System",
            "Changing Corner",
            "Client Seating",
            "Wi-Fi",
            "Marshall Tufton Bluetooth Speaker",
            "Signature Mural Wall",
        ),
        cover_image="/static/studio/arena-lifestyle.jpeg",
        hero_image="/static/studio/arena-lifestyle.jpeg",
        gallery_images=(
            "/static/studio/arena-cyclorama.jpeg",
            "/static/studio/arena-mural.jpeg",
            "/static/studio/arena-backdrop.jpeg",
            "/static/studio/arena-speaker.jpeg",
        ),
        max_duration_hours=10.0,
        booking_purposes=(
            "Fashion Shoot",
            "Family Portraits",
            "Editorial Shoot",
            "Campaign Shoot",
            "Beauty Shoot",
            "Product Shoot",
            "Lifestyle Shoot",
            "Baby Shoot",
            "Reels & Content Creation",
            "Music / Video Production",
            "Creative / Conceptual Shoot",
            "Fine Arts",
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
LEGACY_COVER_IMAGES = {
    "standard_small": (
        "https://images.unsplash.com/photo-1615458509633-f15b61bdacb8"
        "?auto=format&fit=crop&w=1400&q=85"
    ),
    "premium_large": (
        "https://images.unsplash.com/photo-1664817550969-5e76adc4a3fe"
        "?auto=format&fit=crop&w=1400&q=85"
    ),
}
LEGACY_ARENA_CYCLORAMA_LABEL = "Approx. 150 sq. ft. Cyclorama"
PUBLIC_SPACE_CACHE_TTL_SECONDS = 300

_public_space_cache_lock = Lock()
_public_space_cache_expires_at = 0.0
_public_space_list_cache: tuple[StudioSpace, ...] | None = None
_public_space_detail_cache: dict[str, tuple[float, StudioSpace | None]] = {}


def _replace_json_item(value: str, old: str, new: str) -> str:
    items = _json_items(value)
    if old not in items:
        return value
    return json.dumps([new if item == old else item for item in items])


def _position_purpose_after(
    purposes: list[StudioPurposeOption],
    target: StudioPurposeOption,
    preceding_label: str,
) -> None:
    reordered = [purpose for purpose in purposes if purpose is not target]
    preceding_index = next(
        (
            index
            for index, purpose in enumerate(reordered)
            if purpose.label.casefold() == preceding_label.casefold()
        ),
        len(reordered) - 1,
    )
    reordered.insert(preceding_index + 1, target)
    for purpose_order, purpose in enumerate(reordered, start=1):
        purpose.sort_order = purpose_order


def _claim_compatibility_migration(db: Session, migration_key: str) -> bool:
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS app_migrations ("
            "migration_key VARCHAR(120) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
    )
    claimed = db.execute(
        text(
            "INSERT INTO app_migrations (migration_key) VALUES (:migration_key) "
            "ON CONFLICT (migration_key) DO NOTHING"
        ),
        {"migration_key": migration_key},
    )
    return bool(claimed.rowcount)


def seed_studio_settings(db: Session, commit: bool = True) -> None:
    existing = {row.id: row for row in db.scalars(select(StudioSetting))}
    purpose_space_ids = set(db.scalars(select(StudioPurposeOption.space_id).distinct()))
    for sort_order, space in enumerate(SPACES.values(), start=1):
        if space.id in existing:
            row = existing[space.id]
            if row.opening_time == "09:00" and row.closing_time == "20:00":
                row.closing_time = space.closing_time
            if row.id == "premium_large":
                if row.capacity == 10:
                    row.capacity = space.capacity
                row.equipment_json = _replace_json_item(
                    row.equipment_json,
                    LEGACY_ARENA_CYCLORAMA_LABEL,
                    "Cyclorama",
                )
                row.amenities_json = _replace_json_item(
                    row.amenities_json,
                    LEGACY_ARENA_CYCLORAMA_LABEL,
                    "Cyclorama",
                )
            if row.min_duration_hours < MINIMUM_BOOKING_DURATION_HOURS:
                row.min_duration_hours = MINIMUM_BOOKING_DURATION_HOURS
            if row.max_duration_hours < MINIMUM_BOOKING_DURATION_HOURS:
                row.max_duration_hours = MINIMUM_BOOKING_DURATION_HOURS
            legacy_names = LEGACY_SPACE_NAMES.get(space.id, ())
            if row.name in legacy_names:
                row.name = space.name
            if row.slug in LEGACY_SPACE_SLUGS:
                row.slug = LEGACY_SPACE_SLUGS[row.slug]
            if row.cover_image == LEGACY_COVER_IMAGES.get(space.id):
                row.cover_image = space.cover_image
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

    # Migrate the previously added Arena family label and position without
    # replacing any unrelated owner-managed purpose options.
    if _claim_compatibility_migration(db, "rename_and_position_arena_family_portraits"):
        arena_purposes = list(
            db.scalars(
                select(StudioPurposeOption)
                .where(StudioPurposeOption.space_id == "premium_large")
                .order_by(StudioPurposeOption.sort_order, StudioPurposeOption.id)
            )
        )
        old_family_purpose = next(
            (purpose for purpose in arena_purposes if purpose.label.casefold() == "family shoots"),
            None,
        )
        family_purpose = next(
            (
                purpose
                for purpose in arena_purposes
                if purpose.label.casefold() == "family portraits"
            ),
            None,
        )
        should_position_family_purpose = False
        if old_family_purpose is not None:
            if family_purpose is None:
                old_family_purpose.label = "Family Portraits"
                family_purpose = old_family_purpose
            else:
                db.delete(old_family_purpose)
                arena_purposes.remove(old_family_purpose)
            should_position_family_purpose = True
        elif family_purpose is None and arena_purposes:
            family_purpose = StudioPurposeOption(
                space_id="premium_large",
                label="Family Portraits",
                sort_order=max(purpose.sort_order for purpose in arena_purposes) + 1,
            )
            db.add(family_purpose)
            arena_purposes.append(family_purpose)
            should_position_family_purpose = True

        if should_position_family_purpose and family_purpose is not None:
            _position_purpose_after(arena_purposes, family_purpose, "Fashion Shoot")

    # Add Fine Arts to both existing studio purpose lists. If the singular
    # fallback label was previously saved, normalize it instead of duplicating it.
    if _claim_compatibility_migration(db, "add_and_position_fine_arts_purposes"):
        for space_id in ("standard_small", "premium_large"):
            studio_purposes = list(
                db.scalars(
                    select(StudioPurposeOption)
                    .where(StudioPurposeOption.space_id == space_id)
                    .order_by(StudioPurposeOption.sort_order, StudioPurposeOption.id)
                )
            )
            legacy_fine_arts = next(
                (purpose for purpose in studio_purposes if purpose.label.casefold() == "fine art"),
                None,
            )
            fine_arts = next(
                (purpose for purpose in studio_purposes if purpose.label.casefold() == "fine arts"),
                None,
            )
            should_position_fine_arts = False
            if legacy_fine_arts is not None:
                if fine_arts is None:
                    legacy_fine_arts.label = "Fine Arts"
                    fine_arts = legacy_fine_arts
                else:
                    db.delete(legacy_fine_arts)
                    studio_purposes.remove(legacy_fine_arts)
                should_position_fine_arts = True
            elif fine_arts is None and studio_purposes:
                fine_arts = StudioPurposeOption(
                    space_id=space_id,
                    label="Fine Arts",
                    sort_order=max(purpose.sort_order for purpose in studio_purposes) + 1,
                )
                db.add(fine_arts)
                studio_purposes.append(fine_arts)
                should_position_fine_arts = True

            if should_position_fine_arts and fine_arts is not None:
                _position_purpose_after(
                    studio_purposes,
                    fine_arts,
                    "Creative / Conceptual Shoot",
                )

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
    invalidate_public_space_cache()


def list_spaces(db: Session | None = None, include_inactive: bool = False) -> list[StudioSpace]:
    if db is None:
        spaces = list(SPACES.values())
    else:
        statement = select(StudioSetting).order_by(StudioSetting.sort_order, StudioSetting.id)
        rows = list(db.scalars(statement))
        if rows:
            purpose_rows = db.execute(
                select(
                    StudioPurposeOption.space_id,
                    StudioPurposeOption.label,
                ).order_by(
                    StudioPurposeOption.space_id,
                    StudioPurposeOption.sort_order,
                    StudioPurposeOption.id,
                )
            )
            purposes_by_space: dict[str, list[str]] = {}
            for space_id, label in purpose_rows:
                purposes_by_space.setdefault(space_id, []).append(label)
            spaces = [
                _space_from_row(row, tuple(purposes_by_space.get(row.id, ())))
                for row in rows
            ]
        else:
            spaces = list(SPACES.values())
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
    if db is None:
        return next((space for space in SPACES.values() if space.slug == normalized and space.is_active), None)
    row = db.scalar(select(StudioSetting).where(StudioSetting.slug == normalized))
    if row is None or not row.is_active:
        return None
    purposes = tuple(
        db.scalars(
            select(StudioPurposeOption.label)
            .where(StudioPurposeOption.space_id == row.id)
            .order_by(StudioPurposeOption.sort_order, StudioPurposeOption.id)
        )
    )
    return _space_from_row(row, purposes)


def invalidate_public_space_cache() -> None:
    global _public_space_cache_expires_at, _public_space_list_cache
    with _public_space_cache_lock:
        _public_space_cache_expires_at = 0.0
        _public_space_list_cache = None
        _public_space_detail_cache.clear()


def list_public_spaces_cached(db: Session) -> list[StudioSpace]:
    global _public_space_cache_expires_at, _public_space_list_cache
    now = monotonic()
    with _public_space_cache_lock:
        if _public_space_list_cache is not None and now < _public_space_cache_expires_at:
            return list(_public_space_list_cache)

    spaces = list_spaces(db)
    with _public_space_cache_lock:
        _public_space_list_cache = tuple(spaces)
        _public_space_detail_cache.clear()
        expires_at = monotonic() + PUBLIC_SPACE_CACHE_TTL_SECONDS
        _public_space_detail_cache.update((space.slug, (expires_at, space)) for space in spaces)
        _public_space_cache_expires_at = expires_at
    return spaces


def get_public_space_by_slug_cached(slug: str, db: Session) -> StudioSpace | None:
    normalized = LEGACY_SPACE_SLUGS.get(slug.strip().lower(), slug.strip().lower())
    now = monotonic()
    with _public_space_cache_lock:
        if now < _public_space_cache_expires_at:
            if _public_space_list_cache is not None:
                cached = _public_space_detail_cache.get(normalized)
                return cached[1] if cached else None
        cached = _public_space_detail_cache.get(normalized)
        if cached is not None and now < cached[0]:
            return cached[1]

    space = get_space_by_slug(normalized, db)
    with _public_space_cache_lock:
        _public_space_detail_cache[normalized] = (
            monotonic() + PUBLIC_SPACE_CACHE_TTL_SECONDS,
            space,
        )
    return space


def _space_from_row(row: StudioSetting, purposes: tuple[str, ...]) -> StudioSpace:
    default_space = next((space for space in SPACES.values() if space.id == row.id), None)
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
        hero_image=default_space.hero_image if default_space else row.cover_image,
        gallery_images=default_space.gallery_images if default_space else (),
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
