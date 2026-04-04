from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from lxml import html


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
USER_AGENT = "CodexVehicleGenerator/1.0 (https://openai.com)"


def fetch_json(url: str, accept: str | None = None) -> dict:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def normalize_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def wikipedia_root(page: str) -> html.HtmlElement:
    url = (
        "https://en.wikipedia.org/w/api.php?action=parse"
        f"&page={urllib.parse.quote(page)}&prop=text&formatversion=2&format=json"
    )
    payload = fetch_json(url)
    return html.fromstring(payload["parse"]["text"])


def wikipedia_category_titles(category_title: str) -> list[str]:
    titles: list[str] = []
    cmcontinue: str | None = None

    while True:
      url = (
          "https://en.wikipedia.org/w/api.php?action=query&list=categorymembers"
          f"&cmtitle={urllib.parse.quote('Category:' + category_title)}"
          "&cmtype=page&cmlimit=500&format=json"
      )
      if cmcontinue:
          url += f"&cmcontinue={urllib.parse.quote(cmcontinue)}"

      payload = fetch_json(url)
      titles.extend(
          member["title"] for member in payload.get("query", {}).get("categorymembers", [])
      )

      cmcontinue = payload.get("continue", {}).get("cmcontinue")
      if not cmcontinue:
          break

    return titles


def table_names(
    *,
    page: str,
    name_parts: list[int],
    table_indices: list[int] | str = "all",
    skip_exact: set[str] | None = None,
    skip_if_contains: tuple[str, ...] = (),
    limit: int | None = None,
) -> list[dict]:
    root = wikipedia_root(page)
    tables = root.xpath('//table[contains(@class, "wikitable")]')
    indices = range(len(tables)) if table_indices == "all" else table_indices
    items: list[dict] = []
    seen: set[str] = set()
    skip_exact = skip_exact or set()

    for table_index in indices:
        table = tables[table_index]
        for row in table.xpath(".//tr[position()>1]"):
            cells = [
                normalize_text(" ".join(cell.itertext()))
                for cell in row.xpath("./th|./td")
            ]
            if not cells:
                continue

            parts = [cells[index] for index in name_parts if index < len(cells)]
            name = normalize_text(" ".join(part for part in parts if part))
            lowered = name.casefold()

            if not name or name in skip_exact:
                continue
            if any(fragment in lowered for fragment in skip_if_contains):
                continue
            if lowered in seen:
                continue

            seen.add(lowered)
            items.append({"name": name})

            if limit and len(items) >= limit:
                return items

    return items


def category_names(
    *,
    category_titles: list[str],
    skip_exact: set[str] | None = None,
    skip_if_contains: tuple[str, ...] = (),
    limit: int | None = None,
) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    skip_exact = skip_exact or set()

    for category_title in category_titles:
        for name in wikipedia_category_titles(category_title):
            normalized_name = normalize_text(name)
            lowered = normalized_name.casefold()

            if not normalized_name or normalized_name in skip_exact:
                continue
            if any(fragment in lowered for fragment in skip_if_contains):
                continue
            if lowered in seen:
                continue

            seen.add(lowered)
            items.append({"name": normalized_name})

            if limit and len(items) >= limit:
                return items

    return items


def wikidata_family_items(
    *,
    category_qid: str,
    model_qid: str,
    limit: int,
    label_contains_any: tuple[str, ...] = (),
    description_contains_any: tuple[str, ...] = (),
) -> list[dict]:
    query = f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE {{
  ?item wdt:P31 wd:{model_qid} .
  ?item wdt:P279* wd:{category_qid} .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT {limit}
""".strip()
    url = (
        "https://query.wikidata.org/sparql?format=json&query="
        + urllib.parse.quote(query)
    )
    payload = fetch_json(url, "application/sparql-results+json")

    items: list[dict] = []
    seen: set[str] = set()
    for row in payload["results"]["bindings"]:
        label = normalize_text(row["itemLabel"]["value"])
        if re.fullmatch(r"Q\d+", label):
            continue

        description = normalize_text(row.get("itemDescription", {}).get("value", ""))
        lowered_label = label.casefold()
        lowered_description = description.casefold()

        if label_contains_any and not any(
            fragment in lowered_label for fragment in label_contains_any
        ):
            continue
        if description_contains_any and not any(
            fragment in lowered_description for fragment in description_contains_any
        ):
            continue

        if lowered_label in seen:
            continue

        seen.add(lowered_label)
        items.append(
            {
                "name": label,
                "description": description,
            }
        )

    return items


CATEGORIES = [
    {
        "id": "fighter-jets",
        "label": "Fighter Jets",
        "group": "Air",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q14405627",
        "sourceType": "wikidata",
        "categoryQid": "Q14405627",
        "modelQid": "Q15056993",
        "limit": 180,
    },
    {
        "id": "bombers",
        "label": "Bombers",
        "group": "Air",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_bomber_aircraft",
        "sourceType": "table",
        "page": "List of bomber aircraft",
        "tableIndices": [0],
        "nameParts": [0],
        "limit": 220,
    },
    {
        "id": "attack-aircraft",
        "label": "Attack Aircraft",
        "group": "Air",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_attack_aircraft",
        "sourceType": "table",
        "page": "List of attack aircraft",
        "tableIndices": [0],
        "nameParts": [0],
        "limit": 220,
    },
    {
        "id": "military-transports",
        "label": "Military Transports",
        "group": "Air",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_military_transport_aircraft",
        "sourceType": "table",
        "page": "List of military transport aircraft",
        "tableIndices": "all",
        "nameParts": [0],
        "limit": 260,
    },
    {
        "id": "airliners",
        "label": "Airliners",
        "group": "Air",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_commercial_jet_airliners",
        "sourceType": "table",
        "page": "List of commercial jet airliners",
        "tableIndices": [0],
        "nameParts": [0],
        "limit": 160,
    },
    {
        "id": "helicopters",
        "label": "Helicopters",
        "group": "Air",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q34486",
        "sourceType": "wikidata",
        "categoryQid": "Q34486",
        "modelQid": "Q15056993",
        "limit": 180,
    },
    {
        "id": "attack-helicopters",
        "label": "Attack Helicopters",
        "group": "Air",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Attack_helicopters",
        "sourceType": "category",
        "categoryTitles": ["Attack helicopters"],
        "skipExact": {
            "Advanced Attack Helicopter",
            "Attack helicopter",
            "List of military rotorcraft in production and in development by the European defence industry",
        },
        "limit": 120,
    },
    {
        "id": "tanks",
        "label": "Tanks",
        "group": "Land",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_main_battle_tanks_by_generation",
        "sourceType": "table",
        "page": "List of main battle tanks by generation",
        "tableIndices": [0],
        "nameParts": [0],
        "limit": 220,
    },
    {
        "id": "tank-destroyers",
        "label": "Tank Destroyers",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Tank_destroyers",
        "sourceType": "category",
        "categoryTitles": ["Tank destroyers"],
        "skipExact": {
            "Tank destroyer",
            "Anti-tank missile carrier",
            "Missile tank",
            "Self-propelled anti-tank gun",
        },
        "limit": 120,
    },
    {
        "id": "apcs",
        "label": "Armored Personnel Carriers",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Armoured_personnel_carriers",
        "sourceType": "category",
        "categoryTitles": ["Armoured personnel carriers"],
        "skipExact": {"Armoured personnel carrier"},
        "skipContains": ("list of",),
        "limit": 180,
    },
    {
        "id": "ifvs",
        "label": "Infantry Fighting Vehicles",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Infantry_fighting_vehicles",
        "sourceType": "category",
        "categoryTitles": ["Infantry fighting vehicles"],
        "skipExact": {"Infantry fighting vehicle"},
        "skipContains": ("list of",),
        "limit": 180,
    },
    {
        "id": "recon-vehicles",
        "label": "Recon Vehicles",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Reconnaissance_vehicles",
        "sourceType": "category",
        "categoryTitles": ["Reconnaissance vehicles"],
        "skipExact": {"Reconnaissance vehicle", "Scout car"},
        "limit": 180,
    },
    {
        "id": "mraps",
        "label": "MRAPs",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Mine-resistant_ambush_protected_vehicles",
        "sourceType": "category",
        "categoryTitles": ["Mine-resistant ambush protected vehicles"],
        "limit": 180,
    },
    {
        "id": "armored-cars",
        "label": "Armored Cars",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Armoured_cars",
        "sourceType": "category",
        "categoryTitles": ["Armoured cars"],
        "skipExact": {
            "Armored car (military)",
            "Non-military armoured vehicle",
            "Police armored vehicle",
            "Light armoured vehicle",
        },
        "skipContains": ("list of", "company"),
        "limit": 220,
    },
    {
        "id": "rocket-artillery",
        "label": "Rocket Artillery",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Multiple_rocket_launchers",
        "sourceType": "category",
        "categoryTitles": ["Multiple rocket launchers"],
        "skipExact": {"Multiple rocket launcher"},
        "skipContains": ("list of", "rocket-bombs"),
        "limit": 180,
    },
    {
        "id": "self-propelled-artillery",
        "label": "Self-Propelled Artillery",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Self-propelled_artillery",
        "sourceType": "category",
        "categoryTitles": [
            "Self-propelled artillery of the Soviet Union",
            "Self-propelled artillery of the United States",
            "Self-propelled artillery of Germany",
        ],
        "skipExact": {"Samokhodnaya Ustanovka"},
        "limit": 180,
    },
    {
        "id": "amphibious-assault-vehicles",
        "label": "Amphibious Assault Vehicles",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Amphibious_armoured_personnel_carriers",
        "sourceType": "category",
        "categoryTitles": [
            "Amphibious armoured personnel carriers",
            "Amphibious armoured fighting vehicles",
        ],
        "skipExact": {
            "Abbot (artillery)",
            "Amphibious armoured fighting vehicle",
            "FV180 Combat Engineer Tractor",
            "FV434",
            "Template:Tanks converted to armored vehicles",
        },
        "skipContains": ("list of",),
        "limit": 220,
    },
    {
        "id": "sports-cars",
        "label": "Sports Cars",
        "group": "Road",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_sports_cars",
        "sourceType": "table",
        "page": "List of sports cars",
        "tableIndices": [0],
        "nameParts": [0, 1],
        "limit": 700,
    },
    {
        "id": "supercars",
        "label": "Supercars",
        "group": "Road",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q815679",
        "sourceType": "wikidata",
        "categoryQid": "Q815679",
        "modelQid": "Q3231690",
        "limit": 220,
    },
    {
        "id": "race-cars",
        "label": "Race Cars",
        "group": "Road",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q673687",
        "sourceType": "wikidata",
        "categoryQid": "Q673687",
        "modelQid": "Q90834785",
        "limit": 220,
    },
    {
        "id": "muscle-cars",
        "label": "Muscle Cars",
        "group": "Road",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q1072763",
        "sourceType": "wikidata",
        "categoryQid": "Q1072763",
        "modelQid": "Q3231690",
        "limit": 140,
    },
    {
        "id": "pickup-trucks",
        "label": "Pickup Trucks",
        "group": "Road",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_pickup_trucks",
        "sourceType": "table",
        "page": "List of pickup trucks",
        "tableIndices": "all",
        "nameParts": [0, 1],
        "limit": 320,
    },
    {
        "id": "suvs",
        "label": "SUVs",
        "group": "Road",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_sport_utility_vehicles",
        "sourceType": "table",
        "page": "List of sport utility vehicles",
        "tableIndices": "all",
        "nameParts": [0, 1],
        "limit": 420,
    },
    {
        "id": "buses",
        "label": "Buses",
        "group": "Road",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_buses",
        "sourceType": "table",
        "page": "List of buses",
        "tableIndices": "all",
        "nameParts": [3, 0],
        "limit": 320,
        "skipExact": {"Manufacturer Bus", "Bus"},
    },
    {
        "id": "locomotives",
        "label": "Locomotives",
        "group": "Rail",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q93301",
        "sourceType": "wikidata",
        "categoryQid": "Q93301",
        "modelQid": "Q19832486",
        "limit": 200,
    },
    {
        "id": "high-speed-trains",
        "label": "High-Speed Trains",
        "group": "Rail",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_high-speed_trains",
        "sourceType": "table",
        "page": "List of high-speed trains",
        "tableIndices": "all",
        "nameParts": [0],
        "skipExact": {"Operated", "Designed", "Record", "Name"},
        "limit": 220,
    },
    {
        "id": "sailboats",
        "label": "Sailboats",
        "group": "Sea",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_sailing_boat_types",
        "sourceType": "table",
        "page": "List of sailing boat types",
        "tableIndices": "all",
        "nameParts": [0],
        "limit": 260,
    },
    {
        "id": "submarines",
        "label": "Submarines",
        "group": "Sea",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q2811",
        "sourceType": "wikidata",
        "categoryQid": "Q2811",
        "modelQid": "Q1428357",
        "limit": 180,
    },
    {
        "id": "aircraft-carriers",
        "label": "Aircraft Carriers",
        "group": "Sea",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q17205",
        "sourceType": "wikidata",
        "categoryQid": "Q17205",
        "modelQid": "Q559026",
        "descriptionContainsAny": ("aircraft carrier",),
        "limit": 120,
    },
    {
        "id": "spacecraft",
        "label": "Spacecraft",
        "group": "Space",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q40218",
        "sourceType": "wikidata",
        "categoryQid": "Q40218",
        "modelQid": "Q117384805",
        "limit": 180,
    },
]


def fetch_category_items(category: dict) -> list[dict]:
    if category["sourceType"] == "wikidata":
        return wikidata_family_items(
            category_qid=category["categoryQid"],
            model_qid=category["modelQid"],
            limit=category["limit"],
            label_contains_any=tuple(category.get("labelContainsAny", ())),
            description_contains_any=tuple(
                category.get("descriptionContainsAny", ())
            ),
        )

    if category["sourceType"] == "category":
        return category_names(
            category_titles=category["categoryTitles"],
            skip_exact=category.get("skipExact", set()),
            skip_if_contains=tuple(category.get("skipContains", ())),
            limit=category["limit"],
        )

    return table_names(
        page=category["page"],
        table_indices=category.get("tableIndices", "all"),
        name_parts=category["nameParts"],
        skip_exact=category.get("skipExact", set()),
        skip_if_contains=tuple(category.get("skipContains", ())),
        limit=category["limit"],
    )


def merge_items(categories: list[dict]) -> dict:
    vehicles: dict[str, dict] = {}
    category_counts = defaultdict(int)

    for category in categories:
        items = fetch_category_items(category)
        category["_rawCount"] = len(items)

        for item in items:
            name = item["name"]
            key = name.casefold()

            if key not in vehicles:
                vehicles[key] = {
                    "name": name,
                    "description": item.get("description", ""),
                    "categories": [],
                    "groups": [],
                    "sourceLabels": [],
                    "sourceUrls": [],
                }

            record = vehicles[key]
            if not record["description"] and item.get("description"):
                record["description"] = item["description"]

            if category["id"] not in record["categories"]:
                record["categories"].append(category["id"])
                category_counts[category["id"]] += 1

            if category["group"] not in record["groups"]:
                record["groups"].append(category["group"])

            if category["sourceLabel"] not in record["sourceLabels"]:
                record["sourceLabels"].append(category["sourceLabel"])

            if category["sourceUrl"] not in record["sourceUrls"]:
                record["sourceUrls"].append(category["sourceUrl"])

    ordered_vehicles = sorted(
        vehicles.values(),
        key=lambda item: (item["groups"][0], item["name"].casefold()),
    )

    category_records = []
    for category in categories:
        category_records.append(
            {
                "id": category["id"],
                "label": category["label"],
                "group": category["group"],
                "count": category_counts[category["id"]],
                "sourceLabel": category["sourceLabel"],
                "sourceUrl": category["sourceUrl"],
            }
        )

    source_records = []
    seen_sources = set()
    for category in categories:
        key = (category["sourceLabel"], category["sourceUrl"])
        if key in seen_sources:
            continue
        seen_sources.add(key)
        source_records.append(
            {
                "label": category["sourceLabel"],
                "url": category["sourceUrl"],
            }
        )

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "vehicleCount": len(ordered_vehicles),
            "categoryCount": len(category_records),
        },
        "licenses": [
            {
                "label": "Wikidata structured data (CC0)",
                "url": "https://www.wikidata.org/wiki/Wikidata:Main_Page",
            },
            {
                "label": "Wikipedia list pages (CC BY-SA)",
                "url": "https://en.wikipedia.org/wiki/Wikipedia:Copyrights",
            },
        ],
        "sources": source_records,
        "categories": category_records,
        "vehicles": ordered_vehicles,
    }


def main() -> None:
    dataset = merge_items(CATEGORIES)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    json_path = DATA_DIR / "vehicles.json"
    js_path = DATA_DIR / "vehicles.js"

    json_text = json.dumps(dataset, indent=2, ensure_ascii=False)
    json_path.write_text(json_text + "\n", encoding="utf-8")
    js_path.write_text(
        "window.VEHICLE_DATA = " + json.dumps(dataset, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    print(
        f"Built dataset with {dataset['summary']['vehicleCount']} vehicles "
        f"across {dataset['summary']['categoryCount']} categories."
    )


if __name__ == "__main__":
    main()
