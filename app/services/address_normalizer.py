import re
import string

import usaddress


# Map common street suffixes and secondary-unit names to their
# standard USPS abbreviations.
USPS_ABBREVIATIONS = {
    "ALLEY": "ALY",
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "CIRCLE": "CIR",
    "COURT": "CT",
    "DRIVE": "DR",
    "EXPRESSWAY": "EXPY",
    "HIGHWAY": "HWY",
    "LANE": "LN",
    "PARKWAY": "PKWY",
    "PLACE": "PL",
    "PLAZA": "PLZ",
    "ROAD": "RD",
    "SQUARE": "SQ",
    "STREET": "ST",
    "TERRACE": "TER",
    "TRAIL": "TRL",
    "TURNPIKE": "TPKE",
    "APARTMENT": "APT",
    "BUILDING": "BLDG",
    "DEPARTMENT": "DEPT",
    "FLOOR": "FL",
    "ROOM": "RM",
    "SUITE": "STE",
}


def clean_address(raw: str) -> str:
    """Return uppercase address text with normalized punctuation and spacing."""

    # Convert safely to text, uppercase it, and remove surrounding whitespace.
    text = (raw or "").upper().strip()

    # Replace punctuation with spaces while preserving ZIP+4 hyphens.
    punctuation = string.punctuation.replace("-", "")
    translation = str.maketrans(
        punctuation,
        " " * len(punctuation),
    )
    text = text.translate(translation)

    # Replace repeated spaces, tabs, and line breaks with one space.
    return re.sub(r"\s+", " ", text).strip()


def abbreviate_address(cleaned: str) -> str:
    """Apply configured USPS abbreviations to complete words."""

    words = cleaned.split()

    # Words that do not appear in the mapping remain unchanged.
    abbreviated_words = [
        USPS_ABBREVIATIONS.get(word, word)
        for word in words
    ]

    return " ".join(abbreviated_words)


def normalize_address(raw: str) -> dict:
    """
    Clean, normalize, and parse an address.

    Ambiguous, incomplete, or unparseable values are retained and marked
    as needing manual review instead of interrupting the upload.
    """

    # Normalize formatting before parsing so equivalent variants produce
    # the same normalized string.
    cleaned = clean_address(raw)
    normalized = abbreviate_address(cleaned)

    # Empty input cannot be parsed and must be reviewed.
    if not normalized:
        return {
            "normalized": cleaned,
            "street": None,
            "city": None,
            "state": None,
            "zip": None,
            "review_status": "needs_review",
            "address_type": None,
        }

    try:
        # Parse the normalized string into labeled address components.
        parsed, address_type = usaddress.tag(normalized)

        # Construct the street value from available street and unit parts.
        street = " ".join(
            value
            for value in [
                parsed.get("AddressNumber"),
                parsed.get("StreetNamePreDirectional"),
                parsed.get("StreetName"),
                parsed.get("StreetNamePostType"),
                parsed.get("StreetNamePostDirectional"),
                parsed.get("OccupancyType"),
                parsed.get("OccupancyIdentifier"),
            ]
            if value
        )

        # A reliable stored address should be a complete street address.
        is_complete = all(
            [
                parsed.get("AddressNumber"),
                parsed.get("StreetName"),
                parsed.get("PlaceName"),
                parsed.get("StateName"),
                parsed.get("ZipCode"),
            ]
        )

        # Ambiguous and incomplete values remain stored but require review.
        review_status = (
            "unreviewed"
            if address_type == "Street Address" and is_complete
            else "needs_review"
        )

        return {
            "normalized": normalized,
            "street": street or None,
            "city": parsed.get("PlaceName"),
            "state": parsed.get("StateName"),
            "zip": parsed.get("ZipCode"),
            "review_status": review_status,
            "address_type": address_type,
        }

    except (usaddress.RepeatedLabelError, TypeError, ValueError):
        # Keep the normalized text even when component parsing fails.
        return {
            "normalized": normalized or cleaned,
            "street": None,
            "city": None,
            "state": None,
            "zip": None,
            "review_status": "needs_review",
            "address_type": None,
        }