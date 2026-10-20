# SEC regression fixtures

Public SEC Company Facts snapshots retrieved on 2026-10-18 for NVIDIA (1045810), Apple (320193), and Microsoft (789019).

Sources: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json`.
Only supported USD concepts, periods starting on or after 2021-01-01 and filings available by 2026-10-18 are retained. Comparative rows and filing metadata remain intact. Tests cover tag migration, September/June/January fiscal year ends, quarterly YTD subtraction, and broader productive-assets capital expenditure disclosure. These are offline fixtures; tests never query SEC.
