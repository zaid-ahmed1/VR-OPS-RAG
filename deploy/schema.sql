-- VR-OPS performance database schema
-- Run as: psql -U postgres -d vrops -f schema.sql

-- ── Tables ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS trainees (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS sessions (
    id                   SERIAL PRIMARY KEY,
    trainee_id           INTEGER NOT NULL REFERENCES trainees(id) ON DELETE CASCADE,
    date                 TIMESTAMPTZ NOT NULL,
    completion_time_mins NUMERIC NOT NULL DEFAULT 0,
    total_errors         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS session_steps (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL CHECK (step_number BETWEEN 1 AND 12),
    time_mins   NUMERIC,
    appraisal   TEXT CHECK (appraisal IN ('Right', 'Wrong')),
    UNIQUE (session_id, step_number)
);

-- ── Wide view (matches the original Excel column layout) ─────────────────────
-- PostgREST exposes this as GET /performance_wide

CREATE OR REPLACE VIEW performance_wide AS
SELECT
    t.name                                                          AS "Name",
    s.date                                                          AS "Date",
    s.total_errors                                                  AS "Number of errors",
    s.completion_time_mins                                          AS "Completion Time (mins)",
    MAX(CASE WHEN ss.step_number = 1 THEN ss.appraisal END)        AS "Step 1 Appraisal",
    MAX(CASE WHEN ss.step_number = 2 THEN ss.appraisal END)        AS "Step 2 Appraisal",
    MAX(CASE WHEN ss.step_number = 3 THEN ss.appraisal END)        AS "Step 3 Appraisal",
    MAX(CASE WHEN ss.step_number = 4 THEN ss.appraisal END)        AS "Step 4 Appraisal",
    MAX(CASE WHEN ss.step_number = 5 THEN ss.appraisal END)        AS "Step 5 Appraisal",
    MAX(CASE WHEN ss.step_number = 6 THEN ss.appraisal END)        AS "Step 6 Appraisal",
    MAX(CASE WHEN ss.step_number = 7 THEN ss.appraisal END)        AS "Step 7 Appraisal",
    MAX(CASE WHEN ss.step_number = 8 THEN ss.appraisal END)        AS "Step 8 Appraisal",
    MAX(CASE WHEN ss.step_number = 9 THEN ss.appraisal END)        AS "Step 9 Appraisal",
    MAX(CASE WHEN ss.step_number = 10 THEN ss.appraisal END)       AS "Step 10 Appraisal",
    MAX(CASE WHEN ss.step_number = 11 THEN ss.appraisal END)       AS "Step 11 Appraisal",
    MAX(CASE WHEN ss.step_number = 12 THEN ss.appraisal END)       AS "Step 12 Appraisal",
    MAX(CASE WHEN ss.step_number = 1 THEN ss.time_mins END)        AS "Step 1 Time",
    MAX(CASE WHEN ss.step_number = 2 THEN ss.time_mins END)        AS "Step 2 Time",
    MAX(CASE WHEN ss.step_number = 3 THEN ss.time_mins END)        AS "Step 3 Time",
    MAX(CASE WHEN ss.step_number = 4 THEN ss.time_mins END)        AS "Step 4 Time",
    MAX(CASE WHEN ss.step_number = 5 THEN ss.time_mins END)        AS "Step 5 Time",
    MAX(CASE WHEN ss.step_number = 6 THEN ss.time_mins END)        AS "Step 6 Time",
    MAX(CASE WHEN ss.step_number = 7 THEN ss.time_mins END)        AS "Step 7 Time",
    MAX(CASE WHEN ss.step_number = 8 THEN ss.time_mins END)        AS "Step 8 Time",
    MAX(CASE WHEN ss.step_number = 9 THEN ss.time_mins END)        AS "Step 9 Time",
    MAX(CASE WHEN ss.step_number = 10 THEN ss.time_mins END)       AS "Step 10 Time",
    MAX(CASE WHEN ss.step_number = 11 THEN ss.time_mins END)       AS "Step 11 Time",
    MAX(CASE WHEN ss.step_number = 12 THEN ss.time_mins END)       AS "Step 12 Time"
FROM sessions s
JOIN trainees t ON t.id = s.trainee_id
LEFT JOIN session_steps ss ON ss.session_id = s.id
GROUP BY s.id, t.name, s.date, s.total_errors, s.completion_time_mins
ORDER BY s.date;

-- ── Read-only API role ────────────────────────────────────────────────────────
-- Password is set by setup.sh via \set and passed as :api_password

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vrops_api') THEN
        CREATE ROLE vrops_api NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO vrops_api;
GRANT SELECT ON performance_wide TO vrops_api;
GRANT SELECT ON trainees, sessions, session_steps TO vrops_api;

-- ── Authenticator role (PostgREST connects as this) ──────────────────────────
-- The actual password is injected by setup.sh

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vrops_authenticator') THEN
        CREATE ROLE vrops_authenticator NOINHERIT LOGIN;
    END IF;
END
$$;

GRANT vrops_api TO vrops_authenticator;
