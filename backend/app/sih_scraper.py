import re
from typing import Optional

import requests
from bs4 import BeautifulSoup


OFFICIAL_URL = "https://www.sih.gov.in/sih2026PS"

# SIH-derived fallback dataset.
# Used because SIH blocks cloud-provider IPs such as Render.
FALLBACK_URL = (
    "https://raw.githubusercontent.com/"
    "Zaidusyy/sih-2026-problem-statements/"
    "main/data/problem-statements.json"
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sih.gov.in/",
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_count(value: str):
    m = re.search(
        r"(\d[\d,]*)\s*/\s*(\d[\d,]*)",
        value or ""
    )

    if not m:
        return None, None

    return (
        int(m.group(1).replace(",", "")),
        int(m.group(2).replace(",", "")),
    )


def normalize_header(value: str) -> str:
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return value


def header_index(
    headers: list[str],
    *names: str
) -> Optional[int]:

    wanted = {
        normalize_header(name)
        for name in names
    }

    for i, header in enumerate(headers):

        if normalize_header(header) in wanted:
            return i

    return None


def normalize_record(record):
    """
    Convert fallback JSON format into our database format.
    """

    ps_id = clean(
        str(
            record.get("psNumber")
            or record.get("ps_id")
            or ""
        )
    )

    title = clean(
        str(
            record.get("title")
            or ""
        )
    )

    organization = clean(
        str(
            record.get("organisation")
            or record.get("organization")
            or ""
        )
    )

    category = clean(
        str(
            record.get("category")
            or ""
        )
    ).capitalize()

    theme = clean(
        str(
            record.get("theme")
            or ""
        )
    )

    submitted = record.get("submitted")

    capacity = (
        record.get("cap")
        or record.get("capacity")
        or 500
    )

    deadline = clean(
        str(
            record.get("deadline")
            or ""
        )
    )

    description = str(
        record.get("description")
        or ""
    )

    if not re.fullmatch(r"SIH\d{5,}", ps_id):
        return None

    if category not in ("Software", "Hardware"):
        return None

    try:
        submitted = int(submitted)
        capacity = int(capacity)
    except (TypeError, ValueError):
        return None

    return {
        "ps_id": ps_id,
        "title": title,
        "organization": organization,
        "department": clean(
            str(record.get("department") or "")
        ),
        "category": category,
        "theme": theme,
        "submitted": submitted,
        "capacity": capacity,
        "deadline": deadline,
        "description": description,
    }


def fetch_from_official():
    """
    Try the official SIH page.

    This may fail from Render because SIH/Cloudflare
    blocks cloud-provider IP addresses.
    """

    session = requests.Session()
    session.headers.update(HEADERS)

    # Establish normal SIH session/cookies.
    try:
        session.get(
            "https://www.sih.gov.in/",
            timeout=20,
        )
    except requests.RequestException:
        pass

    response = session.get(
        OFFICIAL_URL,
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    records = []

    for table in soup.find_all("table"):

        header_row = table.find("tr")

        if not header_row:
            continue

        headers = [
            clean(
                c.get_text(
                    " ",
                    strip=True,
                )
            )
            for c in header_row.find_all(
                ["th", "td"]
            )
        ]

        normalized = {
            normalize_header(h)
            for h in headers
        }

        required = {
            "organization",
            "problem statement title",
            "category",
            "ps number",
            "submitted idea s count",
            "theme",
            "deadline for idea submission",
        }

        if not required.issubset(normalized):
            continue

        idx_org = header_index(
            headers,
            "Organization",
        )

        idx_title = header_index(
            headers,
            "Problem Statement Title",
        )

        idx_category = header_index(
            headers,
            "Category",
        )

        idx_ps = header_index(
            headers,
            "PS Number",
        )

        idx_count = header_index(
            headers,
            "Submitted Idea(s) Count",
        )

        idx_theme = header_index(
            headers,
            "Theme",
        )

        idx_deadline = header_index(
            headers,
            "Deadline for Idea Submission",
        )

        indexes = [
            idx_org,
            idx_title,
            idx_category,
            idx_ps,
            idx_count,
            idx_theme,
            idx_deadline,
        ]

        if any(i is None for i in indexes):
            continue

        for tr in table.find_all("tr")[1:]:

            cells = tr.find_all("td")

            values = [
                clean(
                    c.get_text(
                        " ",
                        strip=True,
                    )
                )
                for c in cells
            ]

            if len(values) <= max(indexes):
                continue

            ps_id = values[idx_ps]

            if not re.fullmatch(
                r"SIH\d{5,}",
                ps_id,
            ):
                continue

            category = values[
                idx_category
            ].capitalize()

            if category not in (
                "Software",
                "Hardware",
            ):
                continue

            submitted, capacity = parse_count(
                values[idx_count]
            )

            if submitted is None:
                continue

            records.append(
                {
                    "ps_id": ps_id,
                    "title": values[idx_title],
                    "organization": values[idx_org],
                    "department": "",
                    "category": category,
                    "theme": values[idx_theme],
                    "submitted": submitted,
                    "capacity": capacity,
                    "deadline": values[idx_deadline],
                    "description": "",
                }
            )

        if records:
            break

    if not records:
        raise RuntimeError(
            "Official SIH page was reachable but "
            "no problem-statement table was found."
        )

    return records


def fetch_from_fallback():
    """
    Fetch the SIH-derived structured dataset.

    This is used when the official SIH site blocks
    the Render/cloud IP.
    """

    response = requests.get(
        FALLBACK_URL,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise RuntimeError(
            "Fallback SIH dataset has invalid format."
        )

    records = []

    for item in data:

        record = normalize_record(item)

        if record:
            records.append(record)

    if not records:
        raise RuntimeError(
            "Fallback dataset returned zero valid "
            "problem statements."
        )

    return records


def fetch_problem_statements():

    # -------------------------------------------------
    # 1. Try official SIH source first
    # -------------------------------------------------

    try:

        records = fetch_from_official()

        print(
            f"[SIH] Official source: "
            f"{len(records)} records"
        )

        return records

    except Exception as official_error:

        print(
            "[SIH] Official source unavailable: "
            f"{official_error}"
        )

    # -------------------------------------------------
    # 2. Fallback to SIH-derived structured dataset
    # -------------------------------------------------

    try:

        records = fetch_from_fallback()

        print(
            f"[SIH] Fallback source: "
            f"{len(records)} records"
        )

        return records

    except Exception as fallback_error:

        raise RuntimeError(
            "Both SIH sources failed. "
            f"Official error: {official_error}; "
            f"Fallback error: {fallback_error}"
        )