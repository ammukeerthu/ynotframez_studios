from dataclasses import dataclass


@dataclass(frozen=True)
class StudioSpace:
    id: str
    name: str
    brochure: str
    rules: str
    hourly_rate: int


SPACES = {
    "1": StudioSpace(
        id="standard_small",
        name="Standard Small Space",
        brochure=(
            "Standard Small Space: compact studio for portraits, reels, product shoots, and small teams. "
            "Includes basic lights, backdrop support, changing corner, and seating for 4."
        ),
        rules=(
            "Rules: arrive on time, no smoking, no wall damage, clean up props, keep music moderate, "
            "and overtime is charged hourly if available."
        ),
        hourly_rate=1200,
    ),
    "2": StudioSpace(
        id="premium_large",
        name="Premium Large Space",
        brochure=(
            "Premium Large Space: larger studio for fashion, maternity, campaigns, videos, and bigger teams. "
            "Includes premium lighting setup, multiple backdrops, makeup area, lounge seating, and space for 10."
        ),
        rules=(
            "Rules: prior approval needed for heavy props, confetti, smoke, pets, or food setups. "
            "No drilling, painting, unsafe electricals, or unmanaged crowding."
        ),
        hourly_rate=2500,
    ),
}


def list_spaces_message() -> str:
    return (
        "Welcome to our studio booking assistant.\n\n"
        "Please select a space:\n"
        "1. Standard Small Space\n"
        "2. Premium Large Space\n\n"
        "Reply with 1 or 2."
    )


def get_space_by_input(value: str) -> StudioSpace | None:
    normalized = value.strip().lower()
    if normalized in SPACES:
        return SPACES[normalized]
    for space in SPACES.values():
        if normalized in {space.id, space.name.lower()}:
            return space
    return None


def get_space_by_id(space_id: str | None) -> StudioSpace | None:
    if not space_id:
        return None
    return next((space for space in SPACES.values() if space.id == space_id), None)

