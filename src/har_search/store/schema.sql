CREATE TABLE IF NOT EXISTS saved_searches (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  criteria_json TEXT NOT NULL,
  weights_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY,
  saved_search TEXT NOT NULL,
  run_at TEXT NOT NULL,
  source TEXT NOT NULL,
  item_count INTEGER NOT NULL,
  excluded_count INTEGER NOT NULL,
  exclusions_json TEXT,
  sold_exclusions_json TEXT,
  dropped_by_must INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS listings (
  snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
  listing_id TEXT NOT NULL,
  mls_number TEXT,
  address TEXT, city TEXT, zip TEXT, subdivision TEXT,
  lat REAL, lon REAL,
  price INTEGER, price_per_sqft REAL,
  beds INTEGER, baths_full INTEGER, baths_half INTEGER,
  sqft INTEGER, lot_sqft INTEGER, year_built INTEGER,
  garage_spaces INTEGER, garage_attached INTEGER, garage_tags_json TEXT, hoa_monthly REAL,
  property_type TEXT, duplex_scope TEXT, status TEXT, days_on_market INTEGER,
  school_rating REAL, tax_rate REAL,
  appraisal_low INTEGER, appraisal_high INTEGER,
  url TEXT,
  score REAL, coverage REAL, why TEXT,
  score_breakdown_json TEXT, valuation_json TEXT, flags_json TEXT,
  PRIMARY KEY (snapshot_id, listing_id)
);

CREATE TABLE IF NOT EXISTS sold_history (
  mls_number TEXT PRIMARY KEY,
  address TEXT, city TEXT, zip TEXT, subdivision TEXT,
  lat REAL, lon REAL,
  list_price INTEGER, sold_price INTEGER NOT NULL, sold_date TEXT NOT NULL,
  sold_price_per_sqft REAL, sqft INTEGER, beds INTEGER, baths_full INTEGER,
  year_built INTEGER, lot_sqft INTEGER, property_type TEXT,
  first_seen TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sold_geo ON sold_history (lat, lon);
CREATE INDEX IF NOT EXISTS idx_sold_sub ON sold_history (subdivision, sold_date);
CREATE INDEX IF NOT EXISTS idx_snapshot_search ON snapshots (saved_search, run_at);

CREATE TABLE IF NOT EXISTS sold_fetches (
  area TEXT PRIMARY KEY,
  fetched_on TEXT NOT NULL
);

-- The corpus: every active listing ever fetched for any area, keyed on the
-- listing rather than the run that found it. `listings` records which
-- listings a snapshot returned; this records what exists to be searched.
CREATE TABLE IF NOT EXISTS active_listings (
  listing_id TEXT PRIMARY KEY,
  mls_number TEXT,
  address TEXT, city TEXT, zip TEXT, subdivision TEXT,
  lat REAL, lon REAL,
  price INTEGER, price_per_sqft REAL,
  beds INTEGER, baths_full INTEGER, baths_half INTEGER,
  sqft INTEGER, lot_sqft INTEGER, year_built INTEGER,
  garage_spaces INTEGER, garage_attached INTEGER, garage_tags_json TEXT,
  hoa_monthly REAL,
  property_type TEXT, duplex_scope TEXT, status TEXT, days_on_market INTEGER,
  school_rating REAL, tax_rate REAL,
  appraisal_low INTEGER, appraisal_high INTEGER,
  url TEXT, flags_json TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_active_geo ON active_listings (lat, lon);

CREATE TABLE IF NOT EXISTS corpus_fetches (
  area TEXT PRIMARY KEY,
  fetched_on TEXT NOT NULL
);

-- Which areas a corpus listing was found under. The corpus is a union of
-- area fetches, not one pile: a search for one area must not rank another
-- area's listings just because both happen to be cached.
CREATE TABLE IF NOT EXISTS corpus_areas (
  area TEXT NOT NULL,
  listing_id TEXT NOT NULL,
  PRIMARY KEY (area, listing_id)
);
