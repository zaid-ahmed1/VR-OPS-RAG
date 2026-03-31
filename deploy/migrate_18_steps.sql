-- Migration: expand from 12 steps to 18 and grant INSERT to API role
-- Run as: psql -U postgres -d vrops -f migrate_18_steps.sql

-- ── 1. Expand step_number constraint from 1-12 to 1-18 ──────────────────────

ALTER TABLE session_steps DROP CONSTRAINT IF EXISTS session_steps_step_number_check;
ALTER TABLE session_steps ADD CONSTRAINT session_steps_step_number_check
    CHECK (step_number BETWEEN 1 AND 18);

-- ── 2. Grant INSERT so the Unity app can write via PostgREST ─────────────────

GRANT INSERT ON trainees, sessions, session_steps TO vrops_api;
GRANT USAGE, SELECT ON SEQUENCE trainees_id_seq, sessions_id_seq, session_steps_id_seq TO vrops_api;

-- ── 3. Rebuild the wide view with 18 steps ───────────────────────────────────

CREATE OR REPLACE VIEW performance_wide AS
SELECT
    t.name                                                          AS "Name",
    s.date                                                          AS "Date",
    s.total_errors                                                  AS "Number of errors",
    s.completion_time_mins                                          AS "Completion Time (mins)",
    MAX(CASE WHEN ss.step_number =  1 THEN ss.appraisal END)       AS "Step 1 Appraisal",
    MAX(CASE WHEN ss.step_number =  2 THEN ss.appraisal END)       AS "Step 2 Appraisal",
    MAX(CASE WHEN ss.step_number =  3 THEN ss.appraisal END)       AS "Step 3 Appraisal",
    MAX(CASE WHEN ss.step_number =  4 THEN ss.appraisal END)       AS "Step 4 Appraisal",
    MAX(CASE WHEN ss.step_number =  5 THEN ss.appraisal END)       AS "Step 5 Appraisal",
    MAX(CASE WHEN ss.step_number =  6 THEN ss.appraisal END)       AS "Step 6 Appraisal",
    MAX(CASE WHEN ss.step_number =  7 THEN ss.appraisal END)       AS "Step 7 Appraisal",
    MAX(CASE WHEN ss.step_number =  8 THEN ss.appraisal END)       AS "Step 8 Appraisal",
    MAX(CASE WHEN ss.step_number =  9 THEN ss.appraisal END)       AS "Step 9 Appraisal",
    MAX(CASE WHEN ss.step_number = 10 THEN ss.appraisal END)       AS "Step 10 Appraisal",
    MAX(CASE WHEN ss.step_number = 11 THEN ss.appraisal END)       AS "Step 11 Appraisal",
    MAX(CASE WHEN ss.step_number = 12 THEN ss.appraisal END)       AS "Step 12 Appraisal",
    MAX(CASE WHEN ss.step_number = 13 THEN ss.appraisal END)       AS "Step 13 Appraisal",
    MAX(CASE WHEN ss.step_number = 14 THEN ss.appraisal END)       AS "Step 14 Appraisal",
    MAX(CASE WHEN ss.step_number = 15 THEN ss.appraisal END)       AS "Step 15 Appraisal",
    MAX(CASE WHEN ss.step_number = 16 THEN ss.appraisal END)       AS "Step 16 Appraisal",
    MAX(CASE WHEN ss.step_number = 17 THEN ss.appraisal END)       AS "Step 17 Appraisal",
    MAX(CASE WHEN ss.step_number = 18 THEN ss.appraisal END)       AS "Step 18 Appraisal",
    MAX(CASE WHEN ss.step_number =  1 THEN ss.time_mins END)       AS "Step 1 Time",
    MAX(CASE WHEN ss.step_number =  2 THEN ss.time_mins END)       AS "Step 2 Time",
    MAX(CASE WHEN ss.step_number =  3 THEN ss.time_mins END)       AS "Step 3 Time",
    MAX(CASE WHEN ss.step_number =  4 THEN ss.time_mins END)       AS "Step 4 Time",
    MAX(CASE WHEN ss.step_number =  5 THEN ss.time_mins END)       AS "Step 5 Time",
    MAX(CASE WHEN ss.step_number =  6 THEN ss.time_mins END)       AS "Step 6 Time",
    MAX(CASE WHEN ss.step_number =  7 THEN ss.time_mins END)       AS "Step 7 Time",
    MAX(CASE WHEN ss.step_number =  8 THEN ss.time_mins END)       AS "Step 8 Time",
    MAX(CASE WHEN ss.step_number =  9 THEN ss.time_mins END)       AS "Step 9 Time",
    MAX(CASE WHEN ss.step_number = 10 THEN ss.time_mins END)       AS "Step 10 Time",
    MAX(CASE WHEN ss.step_number = 11 THEN ss.time_mins END)       AS "Step 11 Time",
    MAX(CASE WHEN ss.step_number = 12 THEN ss.time_mins END)       AS "Step 12 Time",
    MAX(CASE WHEN ss.step_number = 13 THEN ss.time_mins END)       AS "Step 13 Time",
    MAX(CASE WHEN ss.step_number = 14 THEN ss.time_mins END)       AS "Step 14 Time",
    MAX(CASE WHEN ss.step_number = 15 THEN ss.time_mins END)       AS "Step 15 Time",
    MAX(CASE WHEN ss.step_number = 16 THEN ss.time_mins END)       AS "Step 16 Time",
    MAX(CASE WHEN ss.step_number = 17 THEN ss.time_mins END)       AS "Step 17 Time",
    MAX(CASE WHEN ss.step_number = 18 THEN ss.time_mins END)       AS "Step 18 Time"
FROM sessions s
JOIN trainees t ON t.id = s.trainee_id
LEFT JOIN session_steps ss ON ss.session_id = s.id
GROUP BY s.id, t.name, s.date, s.total_errors, s.completion_time_mins
ORDER BY s.date;

-- Re-grant SELECT on the rebuilt view
GRANT SELECT ON performance_wide TO vrops_api;
