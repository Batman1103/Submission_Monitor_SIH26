import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.sih.gov.in/sih2026PS"
HEADERS = {
    "User-Agent": "SIH-Submission-Monitor/2.0 (official-page polling; respectful requests)"
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_count(value: str):
    m = re.search(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)", value or "")
    if not m:
        return None, None
    return int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))


def normalize_header(value: str) -> str:
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return value


def header_index(headers: list[str], *names: str) -> Optional[int]:
    wanted = {normalize_header(n) for n in names}
    for i, header in enumerate(headers):
        if normalize_header(header) in wanted:
            return i
    return None


def fetch_problem_statements():
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    records = []

    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if not header_row:
            continue

        headers = [clean(c.get_text(" ", strip=True)) for c in header_row.find_all(["th", "td"])]
        normalized = {normalize_header(h) for h in headers}

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

        idx_org = header_index(headers, "Organization")
        idx_title = header_index(headers, "Problem Statement Title")
        idx_category = header_index(headers, "Category")
        idx_ps = header_index(headers, "PS Number")
        idx_count = header_index(headers, "Submitted Idea(s) Count")
        idx_theme = header_index(headers, "Theme")
        idx_deadline = header_index(headers, "Deadline for Idea Submission")

        indexes = [idx_org, idx_title, idx_category, idx_ps, idx_count, idx_theme, idx_deadline]
        if any(i is None for i in indexes):
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all("td")
            values = [clean(c.get_text(" ", strip=True)) for c in cells]
            if len(values) <= max(indexes):
                continue

            ps_id = values[idx_ps]
            if not re.fullmatch(r"SIH\d{5,}", ps_id):
                continue

            category = values[idx_category].capitalize()
            if category not in ("Software", "Hardware"):
                continue

            submitted, capacity = parse_count(values[idx_count])
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

        # The SIH page currently has one table matching this schema. Stop after
        # finding it so unrelated tables on the page cannot contaminate data.
        if records:
            break

    unique = {}
    for record in records:
        unique[record["ps_id"]] = record

    return list(unique.values())
