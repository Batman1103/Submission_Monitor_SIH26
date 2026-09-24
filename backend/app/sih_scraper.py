import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.sih.gov.in/sih2026PS"

# Browser-like headers.
# The previous custom "SIH-Submission-Monitor" User-Agent could be
# rejected by the SIH server/WAF.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.sih.gov.in/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_count(value: str):
    """
    Parses values such as:

        169/500
        169 / 500
        1,169 / 1,500
    """
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


def fetch_problem_statements():

    session = requests.Session()
    session.headers.update(HEADERS)

    # First request to the main SIH domain.
    # This can establish normal session cookies before requesting
    # the problem-statement page.
    try:
        session.get(
            "https://www.sih.gov.in/",
            timeout=30,
        )
    except requests.RequestException:
        # If the homepage fails, still try the actual endpoint.
        pass

    response = session.get(
        SOURCE_URL,
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    records = []

    for table in soup.find_all("table"):

        header_row = table.find("tr")

        if not header_row:
            continue

        headers = [
            clean(c.get_text(" ", strip=True))
            for c in header_row.find_all(["th", "td"])
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
                clean(c.get_text(" ", strip=True))
                for c in cells
            ]

            if len(values) <= max(indexes):
                continue

            ps_id = values[idx_ps]

            if not re.fullmatch(
                r"SIH\d{5,}",
                ps_id
            ):
                continue

            category = values[idx_category].capitalize()

            if category not in (
                "Software",
                "Hardware",
            ):
                continue

            submitted, capacity = parse_count(
                values[idx_count]
            )

            if submitted is None or capacity is None:
                continue

            records.append({
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
            })

        # Stop after finding the table matching
        # the expected SIH schema.
        if records:
            break

    # Remove duplicate PS numbers.
    unique = {}

    for record in records:
        unique[record["ps_id"]] = record

    return list(unique.values())