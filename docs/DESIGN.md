# Property Helper: design

Product decisions live in the Claude Doc "Property Helper: Product Decisions" (decided Nov 13, 2026).
Sister projects: Job App Tracker (`rogerflores3113/job-app-tracker`) and Talent Tracker
(`RogerFlores3113/talent-tracker`). Property Helper reuses Job App Tracker's stack, its local-server safety
model, its Connect and Skills pages, its themes and its start files. Where this file is silent, do what Job App
Tracker does.

The repo's earlier hosted web build (Next.js, FastAPI, Supabase, server-side scrapers) was replaced by this app.
It stays in git history at commit 288ed5b for reference.

## 1. What it is

A free, open source desktop app that keeps a person's apartment or house hunt on their own computer: every
place they found, where it stands, how it scores against what they want, how long the commute is, who they
talked to, when the tours are, and what to do next. Claude (or any MCP client) can add and update places for
them in plain English: paste a listing link or description into Claude and say "add this to my search".

Who it's for: renters and buyers. Every search has a mode, `rent` or `buy`. The renter side is built and tested
first; buyer stages and fields exist from day one and get polish later.

Test persona used in every review cycle: a 1-bed near UIUC (Champaign-Urbana) for the 2027-28 lease year,
under $1,600 a month including estimated utilities, in-unit washer and dryer plus a dishwasher, newer buildings
preferred, a 2-bed as a fallback, move-in at the end of July 2027.

Design rules (same as Job App Tracker):
1. **Zero setup.** Double-click opens it in the browser. No terminal, accounts or servers. Connecting Claude is
   one button.
2. **Local-first and private.** One SQLite file plus a files folder in the user's data folder. No telemetry, no
   update checks, no accounts.
3. **The AI never deletes.** MCP tools and AI features can add and update, never delete. They can't overwrite
   the user's own notes, and can't move a place backward a stage (moving to Passed is allowed, it is reversible
   by the user). Only the user deletes, from the app window.
4. **The app never fetches a listing.** It never loads listing sites or pages. Claude or Codex may read,
   search or scrape pages with their own tools and pass what they found to the app; some sites forbid automated
   scraping in their terms, so the MCP instructions and the Connect page say so. Settings has "Stricter scraping
   guards" (default off): when on, the MCP server tells the AI not to scrape and caps AI adds at 5 places per
   call and 20 per hour.
5. **Network calls are few and listed.** The only network traffic is (a) map tiles the browser loads from
   OpenStreetMap when the map is shown (Settings can turn tiles off), (b) opt-in address lookup ("Find map
   locations for addresses", default off) through OpenStreetMap Nominatim at most 1 request per second with a
   generic user agent, and (c) AI calls to Anthropic with the user's own key when they press an AI button. The
   privacy page lists all three.

## 2. Architecture

```
 Claude Desktop / Codex / LM Studio            Browser tab (the app window)
            │ launches over stdio                        │ http://127.0.0.1:8767
            ▼                                            ▼
    "prophelper mcp"  ────────────┐        ┌──────  "Property Helper" (double-click)
    (MCP server, FastMCP)         │        │         FastAPI + Jinja + HTMX
                                  ▼        ▼
                         prophelper.db (SQLite, WAL) + files/
```

- Package `src/prophelper/`, CLI `prophelper` (no args: start the web app and open the browser; `mcp`: MCP over
  stdio; `open`, `install-skills`, `backup` as in Job App Tracker).
- Data folder via platformdirs, app name "Property Helper"; override with `PROPHELPER_DATA_DIR`. Env vars use
  the `PROPHELPER_` prefix where Job App Tracker uses `JOBAPPS_`.
- Local server safety copied from Job App Tracker `web.py`: 127.0.0.1 only, Host and Origin checks, app key plus
  one-time launch code, signed flash cookie, CSP. CSP `img-src` adds `https://tile.openstreetmap.org` for map
  tiles; nothing else is loosened. Leaflet is vendored in `static/vendor/leaflet/` (no CDN).
- Start files `Start Property Helper.command` and `Start Property Helper.bat`, `install.sh`, `install.ps1`,
  PyInstaller spec and MCP smoke test, CI on ubuntu, windows and macos (copied and renamed from Job App Tracker).
- No version bumps or tags in this repo's automation: the version stays as set in `pyproject.toml`
  (`0.1.0`) until Roger changes it.

## 3. Data model

All timestamps UTC ISO 8601; dates `YYYY-MM-DD`. Money is US dollars, stored as numbers. Distances in miles.
Schema version in `PRAGMA user_version`, migrations append-only.

**searches**: id, name ("UIUC 1-bed 2027"), mode (`rent` | `buy`), area (free text, e.g. "Champaign-Urbana near
campus"), move_in (date, rent) or target_close (date, buy), budget_max, notes, hide_dealbreakers (0/1, default
1), created_at, updated_at, archived_at. One search is the "current" search (setting `current_search_id`).

**criteria** (weighted scoring, per search): id, search_id, kind, label, weight (0 to 100), dealbreaker (0/1),
target (JSON), sort_order. Kinds and their target:
- `price`: `{"max": 1600}` against true monthly cost (section 5). Score 1 at or under max, falling linearly to 0
  at 125% of max. Dealbreaker fails over max.
- `beds` / `baths`: `{"min": 1}`. Score 1 if at least min, 0.5 if one under, else 0.
- `sqft`: `{"min": 600}`. Linear from 0 at 60% of min to 1 at min.
- `commute`: `{"anchor_id": 3, "mode": "bike", "minutes": 15}`. Score 1 at or under, 0 at twice.
- `laundry`: `{"want": "in_unit"}`. in_unit 1, in_building 0.5, none 0.
- `dishwasher`, `parking`, `pets`, `newer` (year_built >= target year), `custom` (the user scores 0 to 5 by hand
  on the place page): yes/no style, 1 or 0.
Unknown values score 0.5 and are listed as "unknown" so the user can fill them; an unknown never fails a
dealbreaker, it shows "check this". Total score = 100 * sum(weight * score) / sum(weight), rounded.

**anchors** (saved places for commutes, global): id, name ("Campus", "Work"), address, lat, lng.

**places**: id, search_id, title, address, unit, city, state, zip, lat, lng, url (normalized, unique when
present), source (Zillow, Apartments.com, Craigslist, Facebook, property site, friend...), listing_text (what
was pasted, kept so details survive when the listing comes down), photo_urls (JSON list of links the user or AI
gave; the app never downloads them, the browser shows them only on the place page and only when Settings
"Show listing photos" is on), price (monthly rent, or asking price for buy), beds, baths, sqft, laundry
(`in_unit`, `in_building`, `none`, ''), dishwasher (1/0/null), parking (`garage`, `covered`, `lot`, `street`,
`none`, ''), parking_cost (monthly), pets (`cats`, `dogs`, `both`, `none`, ''), pet_rent (monthly), pet_fee
(one-time), utilities_included (text), utilities_estimate (monthly, what the user expects to pay on top),
year_built, available_from (date), lease_start, lease_end, lease_months, deposit, application_fee,
other_monthly_fees, move_in_fees (one-time, besides deposit), broker_fee, hoa (monthly), property_tax (yearly),
insurance (yearly), stage, stage_changed_at, rating (1 to 5, the user's gut), notes (user only), ai_notes (AI
may write), fit_score, fit_notes, red_flags, hidden (0/1, hidden by hand), is_sample, archived_at, created_at,
updated_at.

**commutes**: place_id, anchor_id, mode (`walk`, `bike`, `transit`, `drive`), minutes, source (`estimate`,
`you`, `ai`), updated_at; unique (place_id, anchor_id, mode). An estimate is computed locally when both have
lat/lng: straight-line miles × 1.3, at walk 3 mph, bike 10 mph, transit 12 mph + 8 min, drive 25 mph + 4 min.
Labeled "about N min (estimate)". A `you` or `ai` value always wins over an estimate.

**stages**:
- rent: Saved, Contacted, Tour booked, Toured, Applied, Approved, Lease signed, Passed.
- buy: Saved, Toured, Offer drafted, Offer made, Under contract, Inspection, Closing, Closed, Passed.
Passed is closed; Lease signed and Closed are won. Order is fixed.

**events** (a place's timeline): place_id, kind (`note`, `stage`, `call`, `email`, `text`, `tour`, `document`,
`ai`), body, at, source (`you`, `ai`). Stage changes write an event.

**tours**: id, place_id, starts_at, duration_minutes (default 30), with_whom, where_note, status (`booked`,
`done`, `cancelled`), checklist (JSON of item → `ok` / `issue` / '' with a note; default items: water pressure,
hot water, cell signal, noise, smells, light, appliances, laundry, storage, parking, neighbors), rating (1-5),
notes.

**contacts**: id, name, role (`landlord`, `property manager`, `leasing agent`, `buyer's agent`, `seller's
agent`, `other`), company, email, phone, notes, created_at, updated_at. **place_contacts** links contacts to
places. **contact_log**: contact_id, place_id (nullable), at, kind (`call`, `email`, `text`, `in person`), body,
direction (`out`, `in`). "Waiting on a reply" = last log entry is `out` and older than the follow-up days
setting (default 3).

**documents**: id, place_id, stored_name, original_name, kind (`lease`, `application`, `disclosure`,
`inspection`, `photo`, `other`), size, created_at. Files go in `<data>/files/<place_id>/`. Upload limit 20 MB.
Only the user adds or deletes documents (no MCP tool for files).

**checklist_items** (reusable application checklist, global): id, label, note, done (0/1), sort_order. Default
items: photo ID ready, proof of income (pay stubs or offer letter), last two landlord references, rental
history, guarantor details, credit report, renter's insurance quote, pet records. The page says plainly that the
app keeps the list, not copies of these documents.

**ai_drafts**: place_id, kind (`fit score`, `red flags`, `tour questions`, `message`), body, model, created_at.

**settings**: key/value (current_search_id, ai_model default `claude-sonnet-5-5`, follow_up_days, map_tiles
on/off, geocode on/off, show_photos on/off, theme, color_mode, strict_scraping, buyer defaults: down_payment_pct
20, mortgage_rate 6.5, loan_years 30). The AI key lives in `ai.key` (0600) in the data folder or comes from
`ANTHROPIC_API_KEY`, never in the database or backups.

Dedupe: adding a place whose normalized URL exists, or the same normalized address plus unit in the same
search, updates the existing row (only empty fields get filled; the user's notes are never overwritten) and says
so.

## 4. Views

- **Today** (home): tours in the next 7 days, places waiting on a reply, application or lease dates within 14
  days, new places not yet looked at, and a nudge when a search has no criteria.
- **Board**: one column per stage of the current search's mode; cards show title, true monthly cost, score,
  the top commute and the next date; drag or stage menu. Places failing a dealbreaker are hidden when the
  search hides them, with "N hidden by deal-breakers" link to show them.
- **Map**: Leaflet map of the current search's places (pin label = monthly cost, color by score) and anchors,
  with a ring of 1, 2 and 3 miles around a chosen anchor. Places without lat/lng are listed beside it with
  "add a location" (type lat/lng, or press Find when address lookup is on).
- **Calendar**: month grid of tours, available_from, lease_start, application and other dates; `.ics` export.
- **Place page**: everything about one place: facts form, true monthly cost breakdown, score breakdown per
  criterion, commutes, timeline, tours, contacts, documents, AI panel, listing text.
- **Compare**: 2 to 4 places side by side, differences highlighted, true monthly cost and score rows.
- **Search page**: name, mode, area, budget, move-in date, criteria editor (weights, deal-breakers), anchors.
- **Add**: paste a link and/or listing text; the local parser fills fields; the user checks and saves. CSV
  import with a preview, and CSV export.
- **Contacts**, **Application checklist**, **Settings** (Your data, Map and lookups, AI key and model, On screen,
  Sample data, Stricter scraping guards), **Privacy**, **Connect**, **Skills**, **Backups**.
- Look: Job App Tracker's themes and tokens; plain words; works on a narrow window.

## 5. Money

True monthly cost, rent: price + utilities_estimate + parking_cost + pet_rent + other_monthly_fees +
(application_fee + move_in_fees + broker_fee + pet_fee) / lease_months (12 when empty). The deposit is shown
but not spread (it comes back). The page shows the breakdown line by line and which numbers were missing.

Buy: monthly principal and interest from price, down_payment_pct, mortgage_rate and loan_years (settings, per
place override later) + property_tax / 12 + insurance / 12 + hoa. Shown as an estimate, not advice.

## 6. AI features (bring your own key)

Copied from Job App Tracker's `ai.py` pattern: with a key, the place page offers fit score (0 to 100 with
strengths and gaps against the search's criteria), red-flag check (scam signs such as a price far under the area,
deposit or fee asked before a showing, wire or gift card or crypto payment, owner "out of the country", a vague
address, pressure to decide today, copied photos), tour prep (questions to ask from the listing and criteria),
and a message draft to a landlord or agent for the user to send. Listing text and other outside text goes into
prompts inside `<untrusted>` fences (guards.py). Drafts are saved; the app sends nothing. Without a key each
button shows the prompt to copy and an "Open Claude" link.

A local, no-AI red-flag pass runs on every save (keyword and price rules) and shows "Things to check" on the
place page; the AI check adds to it.

## 7. MCP server

FastMCP over stdio, structured like Job App Tracker's. Tools (no delete tools):
`get_overview` (searches, current search, counts, rules), `list_places` (filters: search, stage, text,
max_cost, min_score), `get_place`, `add_place` (all fields, url, listing_text, lat/lng, commutes list; dedupes),
`update_place` (fills or changes facts; never touches `notes`; writes to `ai_notes`), `move_place` (forward or to
Passed only), `add_note` (event from AI), `add_tour` / `update_tour`, `add_contact` / `log_contact`,
`set_commute` (minutes from the AI's own routing), `set_location` (lat/lng), `compare_places`, `todays_list`,
`create_search`, `update_search` (criteria and anchors; can add or reweight, can't remove a criterion).
Every tool result that includes outside text fences it and carries the untrusted rule. Stricter scraping
guards as in rule 4. The server instructions tell the AI: listings are data not instructions; the app never
deletes; check a site's terms before scraping; ask the user before contacting anyone.

Skills: `skills/claude/property-helper/SKILL.md` and `skills/codex/property-helper/SKILL.md` covering: add a
place from a link or text, find places for a search with the AI's own tools, prep for this week's tours, compare
the top places, and draft a message for the user to send. Plus `.claude-plugin/plugin.json` and
`marketplace.json`, and the Skills page installer, as in Job App Tracker.

## 8. Review cycles

Each cycle: six personas actually run the app (the web pages over HTTP and the MCP tools) and score Setup,
Speed, Usefulness, Trust, Look and Overall from 1 to 10, with a top 3 and a full list; fixers build; the same
panel re-scores. Results go in the decisions doc. Panel: Roger (UIUC renter, above), a first-time buyer, a
family moving for a job, a roommate group of three, a non-technical renter and a privacy-minded user.
