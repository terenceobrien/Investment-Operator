-- Schema for AGENT_STORAGE_BACKEND=postgres
--
-- Design philosophy: JSON-heavy with indexed columns for lookup.
-- Each table has a payload JSONB column containing the full serialized record,
-- plus a few denormalized columns for fast indexed queries.
--
-- This pattern lets schemas evolve (add fields to Pydantic) without DB migrations.
-- Promote fields to native columns only when query patterns demand it.

-- Keyed collections (one row per record_id)

CREATE TABLE IF NOT EXISTS schema_records (
    record_id TEXT PRIMARY KEY,
    schema_type TEXT NOT NULL,
    asof_date TEXT,
    ticker TEXT,
    source_id TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_schema_records_schema_type ON schema_records(schema_type);
CREATE INDEX IF NOT EXISTS ix_schema_records_asof_date ON schema_records(asof_date);
CREATE INDEX IF NOT EXISTS ix_schema_records_ticker ON schema_records(ticker);

CREATE TABLE IF NOT EXISTS trade_outcomes (
    record_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    underlying TEXT NOT NULL,
    status TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_trade_outcomes_cycle_id ON trade_outcomes(cycle_id);
CREATE INDEX IF NOT EXISTS ix_trade_outcomes_status ON trade_outcomes(status);
CREATE INDEX IF NOT EXISTS ix_trade_outcomes_underlying ON trade_outcomes(underlying);

CREATE TABLE IF NOT EXISTS regime_states (
    record_id TEXT PRIMARY KEY,
    asof_date TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_regime_states_asof_date ON regime_states(asof_date);

CREATE TABLE IF NOT EXISTS portfolio_plans (
    record_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_portfolio_plans_cycle_id ON portfolio_plans(cycle_id);

CREATE TABLE IF NOT EXISTS trade_ideas (
    record_id TEXT PRIMARY KEY,
    underlying TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_trade_ideas_underlying ON trade_ideas(underlying);

CREATE TABLE IF NOT EXISTS trade_scenario_analyses (
    record_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_trade_scenario_analyses_trade_id
    ON trade_scenario_analyses(trade_id);

CREATE TABLE IF NOT EXISTS macro_forecast_results (
    record_id TEXT PRIMARY KEY,
    asof_date TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_macro_forecast_results_asof_date
    ON macro_forecast_results(asof_date);

CREATE TABLE IF NOT EXISTS historical_calibration_results (
    record_id TEXT PRIMARY KEY,
    asof_date TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_historical_calibration_results_asof_date
    ON historical_calibration_results(asof_date);

CREATE TABLE IF NOT EXISTS monte_carlo_results (
    record_id TEXT PRIMARY KEY,
    cycle_id TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_monte_carlo_results_cycle_id
    ON monte_carlo_results(cycle_id);

CREATE TABLE IF NOT EXISTS convictions (
    record_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fundamental_analyses (
    record_id TEXT PRIMARY KEY,
    ticker TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_fundamental_analyses_ticker
    ON fundamental_analyses(ticker);

CREATE TABLE IF NOT EXISTS narrative_analyses (
    record_id TEXT PRIMARY KEY,
    ticker TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_narrative_analyses_ticker ON narrative_analyses(ticker);

CREATE TABLE IF NOT EXISTS thematic_maps (
    record_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research_priorities (
    record_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS positions_snapshots (
    record_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scenario_sets (
    record_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clarification_requests (
    record_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fundamental_screens (
    record_id TEXT PRIMARY KEY,
    ticker TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_fundamental_screens_ticker
    ON fundamental_screens(ticker);

-- Catch-all for any keyed collection not enumerated above.
CREATE TABLE IF NOT EXISTS generic_records (
    record_id TEXT NOT NULL,
    collection TEXT NOT NULL,
    payload JSONB NOT NULL,
    indexed_fields JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (collection, record_id)
);
CREATE INDEX IF NOT EXISTS ix_generic_records_collection ON generic_records(collection);

-- Append-only logs (multiple rows per indexed field)

CREATE TABLE IF NOT EXISTS price_points (
    id BIGSERIAL PRIMARY KEY,
    trade_id TEXT NOT NULL,
    asof_date TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_price_points_trade_id ON price_points(trade_id);
CREATE INDEX IF NOT EXISTS ix_price_points_asof_date ON price_points(asof_date);

CREATE TABLE IF NOT EXISTS decision_log_entries (
    id BIGSERIAL PRIMARY KEY,
    cycle_id TEXT,
    candidate TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_decision_log_entries_cycle_id
    ON decision_log_entries(cycle_id);

-- Catch-all for any log not enumerated above.
CREATE TABLE IF NOT EXISTS generic_log_entries (
    id BIGSERIAL PRIMARY KEY,
    log_name TEXT NOT NULL,
    payload JSONB NOT NULL,
    indexed_fields JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_generic_log_entries_log_name
    ON generic_log_entries(log_name);
