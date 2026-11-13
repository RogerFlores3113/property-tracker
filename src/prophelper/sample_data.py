"""Made-up data to look around with. Every row is marked ``is_sample`` and removing it never touches your own entries.

Everything here is fictional: the buildings, the streets and the contact. The map points are only near Champaign-Urbana
so the map has something to show. Nothing here is a real listing, person, phone number or address.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .store import Store

SEARCH_NAME = "UIUC 1-bed 2027-28"
ANCHOR = {"name": "Campus (Main Quad)", "address": "Main Quad, Urbana", "lat": 40.1074, "lng": -88.2272}

# (fields, stage)
PLACES: list[tuple[dict[str, Any], str]] = [
    ({"title": "Maple Row Flats", "address": "410 Maple Row Lane", "city": "Champaign", "state": "IL", "zip": "61820",
      "lat": 40.1102, "lng": -88.2301, "source": "Property site", "price": 1495, "beds": 1, "baths": 1, "sqft": 650,
      "laundry": "in_unit", "dishwasher": 1, "parking": "lot", "pets": "cats", "utilities_estimate": 90, "year_built": 2016,
      "available_from": "2027-07-31", "deposit": 1495, "application_fee": 45, "lease_months": 12,
      "utilities_included": "water and trash",
      "listing_text": "Maple Row Flats (sample). 1 bed, 1 bath, 650 sq ft. Washer and dryer in the unit, dishwasher, off-street "
                      "parking. Cats welcome. $1,495 a month. Available July 31, 2027.",
      "notes": "Friendly leasing office. Ask about the July 31 move-in."}, "Tour booked"),
    ({"title": "Quad View Lofts", "address": "27 Quarry Street", "city": "Champaign", "state": "IL", "zip": "61820",
      "lat": 40.1081, "lng": -88.2245, "source": "Apartments.com", "price": 1780, "beds": 1, "baths": 1, "sqft": 720,
      "laundry": "in_unit", "dishwasher": 1, "parking": "garage", "parking_cost": 90, "pets": "both", "utilities_estimate": 75,
      "year_built": 2019, "available_from": "2027-08-01", "deposit": 1780}, "Saved"),
    ({"title": "Prairie Commons", "address": "1200 Prairie Commons Drive", "city": "Champaign", "state": "IL", "zip": "61822",
      "lat": 40.1190, "lng": -88.2410, "source": "Zillow", "price": 1350, "beds": 1, "baths": 1, "sqft": 600,
      "laundry": "in_building", "dishwasher": 1, "parking": "lot", "pets": "none", "utilities_estimate": 110, "year_built": 2008,
      "available_from": "2027-07-15"}, "Saved"),
    ({"title": "Linden Court Apartments", "address": "905 Linden Court", "city": "Urbana", "state": "IL", "zip": "61801",
      "lat": 40.1030, "lng": -88.2205, "source": "Craigslist", "price": 1150, "beds": 1, "baths": 1, "sqft": 540,
      "laundry": "none", "dishwasher": 0, "parking": "street", "pets": "cats", "utilities_estimate": 130, "year_built": 1998}, "Saved"),
    ({"title": "Orchard Hill Townhomes", "address": "3 Orchard Hill Road", "city": "Champaign", "state": "IL", "zip": "61822",
      "lat": 40.0950, "lng": -88.2380, "source": "Property site", "price": 1590, "beds": 2, "baths": 1.5, "sqft": 900,
      "laundry": "in_unit", "dishwasher": 1, "parking": "garage", "pets": "both", "utilities_estimate": 120, "year_built": 2012,
      "available_from": "2027-07-31", "notes": "A 2-bed fallback if the 1-beds fall through."}, "Contacted"),
    ({"title": "Brickyard Studios", "address": "88 Brickyard Avenue", "city": "Urbana", "state": "IL", "zip": "61801",
      "lat": 40.1065, "lng": -88.2210, "source": "Facebook", "price": 950, "beds": 0, "baths": 1, "sqft": 380,
      "parking": "street", "utilities_estimate": 70,
      "listing_text": "Brickyard Studios (sample). Studio near campus, $950 a month. Ask about laundry."}, "Saved"),
    ({"title": "The Elm Street House", "address": "612 Elm Street", "city": "Champaign", "state": "IL", "zip": "61820",
      "source": "Friend", "price": 1425, "beds": 1, "baths": 1, "laundry": "in_unit",
      "listing_text": "A friend's listing (sample). No exact map point yet, so the place shows under 'add a location'."}, "Saved"),
    ({"title": "Cedar Point Residences", "address": "2001 Cedar Point Parkway", "city": "Champaign", "state": "IL", "zip": "61822",
      "lat": 40.1250, "lng": -88.2100, "source": "Property site", "price": 1560, "beds": 1, "baths": 1, "sqft": 700,
      "laundry": "in_unit", "dishwasher": 1, "parking": "covered", "pets": "both", "utilities_included": "all utilities included",
      "year_built": 2021, "available_from": "2027-07-31", "rating": 4, "notes": "Nice and new, but a longer ride to campus."},
     "Toured"),
    ({"title": "Bright Lakeview Condo", "address": "88 Lakeview Drive", "city": "Champaign", "state": "IL", "zip": "61821",
      "lat": 40.1000, "lng": -88.2300, "source": "Craigslist", "price": 450, "beds": 1, "baths": 1, "sqft": 700,
      "laundry": "in_unit", "dishwasher": 1, "parking": "garage",
      "listing_text": "Beautiful 1 bed condo, only $450 a month! The owner is abroad on a mission and can't show the place. "
                      "Wire the deposit today to hold it and we will mail you the keys. Many people are interested, "
                      "so decide today."}, "Saved"),
    ({"title": "Silo Yard Apartments", "address": "700 Silo Yard Road", "city": "Champaign", "state": "IL", "zip": "61822",
      "lat": 40.0990, "lng": -88.2440, "source": "Zillow", "price": 1520, "beds": 1, "baths": 1, "sqft": 630,
      "laundry": "in_unit", "dishwasher": 1, "parking": "none", "year_built": 2005, "available_from": "2027-08-01"}, "Saved"),
]


def load_sample_data(store: Store) -> int:
    """Add the sample search, anchor, places, a tour and a contact. Returns the number of places added. Makes the
    sample search the current one so the app shows it. Does nothing (returns 0) when sample data is already there."""
    if store.has_sample_data():
        return 0
    search = store.add_search(SEARCH_NAME, "rent", area="Champaign-Urbana near campus", move_in="2027-07-31",
                              budget_max=1600, is_sample=True)
    anchor = store.add_anchor(ANCHOR["name"], ANCHOR["address"], ANCHOR["lat"], ANCHOR["lng"], is_sample=True)
    sid = search["id"]
    store.add_criterion(sid, "price", label="Monthly cost, at most $1,600", weight=30, dealbreaker=True, target={"max": 1600})
    store.add_criterion(sid, "laundry", label="Washer and dryer in the unit", weight=20, dealbreaker=True, target={"want": "in_unit"})
    store.add_criterion(sid, "dishwasher", label="Dishwasher", weight=10)
    store.add_criterion(sid, "commute", label=f"Bike to {ANCHOR['name']}, 15 min or less", weight=25,
                        target={"anchor_id": anchor["id"], "mode": "bike", "minutes": 15})
    store.add_criterion(sid, "beds", label="At least 1 bedroom", weight=10, target={"min": 1})
    store.add_criterion(sid, "newer", label="Built 2010 or later", weight=5, target={"year": 2010})
    store.set_current_search(sid)

    ids: dict[str, int] = {}
    for fields, stage in PLACES:
        place, _ = store.add_place(search_id=sid, is_sample=True, **fields)
        ids[fields["title"]] = place["id"]
        if stage != "Saved":
            store.move_stage(place["id"], stage)
    maple, silo = ids["Maple Row Flats"], ids["Silo Yard Apartments"]
    soon = (datetime.now() + timedelta(days=3)).replace(hour=14, minute=0, second=0, microsecond=0)
    store.add_tour(maple, soon, duration_minutes=30, with_whom="Maple Row leasing office", where_note="Leasing office, front door",
                   advance=False)
    store.add_event(maple, "note", "Sample: asked about a July 31 move-in.", source="you")
    contact = store.add_contact("Maple Row leasing office", role="leasing agent", company="Maple Row Flats",
                                email="leasing@maplerow.example", phone="(555) 010-0142",
                                notes="Sample contact. Not a real person or business.", is_sample=True)
    store.link_contact(maple, contact["id"])
    store.log_contact(contact["id"], "email", "Asked about the July 31 move-in and a tour.", direction="out", place_id=maple,
                      at=datetime.now(timezone.utc) - timedelta(days=5))
    store.add_event(silo, "note", "Sample: the utilities estimate isn't filled in yet, so the cost shows as unknown.", source="you")
    return len(PLACES)
