"""Made-up pasted listings in the shapes the big sites use, with what the parser should find in each.

Every name, street and number here is invented. No real people, phone numbers or email addresses. Dates carry a year
so the tests do not depend on today's date.
"""

FIXTURES = [
    {
        "name": "zillow rental",
        "url": "https://www.zillow.com/apartments/champaign-il/maple-row-flats/9XyZ1/",
        "text": """Skip to main content
Maple Row Flats
410 Maple Row Ln, Champaign, IL 61820
$1,495+/mo
1 bd  1 ba  650 sqft
Request a tour
Save
Overview
Welcome to Maple Row Flats, a newer community built in 2016 a short bike ride from campus.
Available Jul 31, 2027
Facts and features
Laundry: In Unit
Appliances included: Dishwasher, Microwave, Refrigerator
Parking: Off-street, Lot
Pets: Cats allowed
Lease term: 12 months
Security deposit $1,495
Application fee $45
Pet fee: $250 one time. Pet rent: $25/mo
Utilities included: Water, Trash
""",
        "expect": {
            "source": "Zillow", "title": "Maple Row Flats", "price": 1495, "beds": 1, "baths": 1, "sqft": 650,
            "address": "410 Maple Row Ln", "city": "Champaign", "state": "IL", "zip": "61820", "laundry": "in_unit",
            "dishwasher": 1, "parking": "lot", "pets": "cats", "pet_rent": 25, "pet_fee": 250, "deposit": 1495,
            "application_fee": 45, "lease_months": 12, "year_built": 2016, "available_from": "2027-07-31",
            "utilities_included": "water, trash",
        },
    },
    {
        "name": "apartments.com floor plan with ranges and fees",
        "url": "https://www.apartments.com/quarry-street-lofts-champaign-il/abc123/",
        "text": """Quarry Street Lofts
27 Quarry Street, Champaign, IL 61820
Monthly Rent
$1,680 - $2,150
Bedrooms
1 - 2 bd
Bathrooms
1 - 2 ba
Square Feet
720 - 1,140 sq ft
Available Aug 1, 2027
Fees and Policies
Dogs Allowed
Cats Allowed
Pet Fee $300 one-time
Monthly Pet Rent $35
Parking
Garage $95 /mo
Surface Lot Free
Other Fees
Application Fee $50
Administrative Fee $150
Amenity Fee $20 /mo
Security Deposit $500
Features: In Unit Washer & Dryer, Dishwasher, Granite Counters.
Lease Options: 3, 6, 9, 12, 15 months
Water, sewer and trash are included.
""",
        "expect": {
            "source": "Apartments.com", "title": "Quarry Street Lofts", "price": 1680, "beds": 1, "baths": 1, "sqft": 720,
            "address": "27 Quarry Street", "city": "Champaign", "state": "IL", "zip": "61820", "laundry": "in_unit",
            "dishwasher": 1, "parking": "garage", "parking_cost": 95, "pets": "both", "pet_fee": 300, "pet_rent": 35,
            "application_fee": 50, "move_in_fees": 150, "other_monthly_fees": 20, "deposit": 500,
            "available_from": "2027-08-01", "utilities_included": "water, sewer, trash",
        },
        "absent": ["lease_months"],
    },
    {
        "name": "craigslist one-liner",
        "url": "https://champaign.craigslist.org/apa/d/urbana-sunny-1br-near-campus/7712345678.html",
        "text": """Sunny 1BR near campus, off street parking - $1100 / 1br - 700ft2 - (Urbana)
available Aug 15, 2027
cats are OK - purrr
no smoking
w/d hookups
Cozy first floor apartment at 905 Linden Court. Heat included. Street parking only. No dishwasher.
Security deposit $1100. Lease is 12 months.
""",
        "expect": {
            "source": "Craigslist", "price": 1100, "beds": 1, "sqft": 700, "available_from": "2027-08-15", "pets": "cats",
            "address": "905 Linden Court", "dishwasher": 0, "deposit": 1100, "lease_months": 12,
            "utilities_included": "heat", "laundry": "hookups",
        },
    },
    {
        "name": "facebook marketplace studio",
        "url": "https://www.facebook.com/marketplace/item/1234567890/",
        "text": """Studio apartment near campus
$950 / month
Listed 3 days ago in Urbana, IL
Details
Type: Studio
Square feet: 380
Parking: street parking
Quiet building, laundry room in the basement. Utilities not included.
Available now. No pets please.
88 Brickyard Avenue, Unit 4B
""",
        "expect": {
            "source": "Facebook", "price": 950, "beds": 0, "sqft": 380, "laundry": "in_building", "pets": "none",
            "parking": "street", "address": "88 Brickyard Avenue", "unit": "4B",
        },
        "absent": ["utilities_included", "dishwasher"],
        "today": "2027-03-01",
        "expect_today": {"available_from": "2027-03-01"},
    },
    {
        "name": "realtor.com house for sale",
        "url": "https://www.realtor.com/realestateandhomes-detail/3-Orchard-Hill-Rd_Champaign_IL_61822_M12345-67890",
        "text": """$389,900
3 bed  2.5 bath  1,980 sq ft  0.22 acre lot
3 Orchard Hill Rd, Champaign, IL 61822
Est. payment $2,456/mo
Single family home for sale. Built in 1998. Attached 2-car garage, in-unit laundry hookups, dishwasher included.
HOA fee: $240 monthly
Property taxes: $5,310 per year
Lot size: 9,583 sqft
No pets restrictions. Cats and dogs welcome.
""",
        "expect": {
            "source": "Realtor.com", "price": 389900, "beds": 3, "baths": 2.5, "sqft": 1980, "year_built": 1998,
            "address": "3 Orchard Hill Rd", "city": "Champaign", "state": "IL", "zip": "61822", "parking": "garage",
            "dishwasher": 1, "hoa": 240, "property_tax": 5310, "pets": "both", "laundry": "hookups",
        },
    },
    {
        "name": "redfin condo with full and half baths",
        "url": "https://www.redfin.com/IL/Champaign/512-Elm-St-61820/unit-3A/home/1111",
        "text": """512 Elm St #3A
Champaign, IL 61820
$245,000
Price
2 Beds
1 full, 1 half Baths
1,150 Sq Ft
Year Built: 2004
HOA Dues: $1,800/yr
Taxes: $3,120/yr
Mortgage payment: $1,610/mo
Covered parking. Washer and dryer in unit.
""",
        "expect": {
            "source": "Redfin", "price": 245000, "beds": 2, "baths": 1.5, "sqft": 1150, "year_built": 2004,
            "address": "512 Elm St", "unit": "3A", "city": "Champaign", "state": "IL", "zip": "61820", "hoa": 150,
            "property_tax": 3120, "parking": "covered", "laundry": "in_unit",
        },
    },
    {
        "name": "property manager site",
        "url": "https://www.cedarpointresidences.example/floorplans/b2",
        "text": """Cedar Point Residences | The B2 Floor Plan
2001 Cedar Point Parkway, Champaign, IL 61822
Starting at $1,560 per month
1 Bedroom | 1 Bathroom | 700 SF
Move-in date: 7/31/2027
New in 2021. All utilities included. Washer/dryer included in every home. Dishwasher.
Covered parking is $45 per month. Pet friendly: $300 pet deposit and $30 pet rent per pet.
12-month lease. $200 refundable security deposit. Application fee: $40.
""",
        "expect": {
            "source": "cedarpointresidences.example", "price": 1560, "beds": 1, "baths": 1, "sqft": 700,
            "address": "2001 Cedar Point Parkway", "city": "Champaign", "state": "IL", "zip": "61822",
            "available_from": "2027-07-31", "utilities_included": "all utilities included", "laundry": "in_unit",
            "dishwasher": 1, "parking": "covered", "parking_cost": 45, "pets": "both", "pet_deposit": 300, "pet_rent": 30,
            "lease_months": 12, "deposit": 200, "application_fee": 40,
        },
    },
    {
        "name": "per bed student housing is not the rent",
        "url": "",
        "text": """The Collective on Green
Rates from $749/bed. 4 bed 4 bath
Furnished apartments. Utilities capped at $60 per month.
""",
        "expect": {"beds": 4, "baths": 4},
        "absent": ["price"],
    },
    {
        "name": "scam looking listing still parses",
        "url": "https://www.example-listings.test/ad/42",
        "text": """BEAUTIFUL 3 bedroom house only $600 a month!!!
The owner is out of the country on a mission and cannot show it. Wire the deposit today, we will mail you the keys.
Many people interested, decide today. Zelle only.
""",
        "expect": {"price": 600, "beds": 3, "source": "example-listings.test"},
        "absent": ["address"],
    },
    {
        "name": "no dishwasher and no in-unit laundry",
        "url": "",
        "text": """2 bedroom 1 bath upstairs apartment, 880 sq ft, $1,325/mo. No in-unit laundry, but there is a laundry room on site.
No dishwasher. Pets: No. No garage. Free parking.
""",
        "expect": {"price": 1325, "beds": 2, "baths": 1, "sqft": 880, "laundry": "in_building", "dishwasher": 0,
                   "pets": "none", "parking": "lot", "parking_cost": 0},
    },
]
