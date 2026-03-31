-- Grant INSERT so the Unity app can write via PostgREST
-- Run as: psql -U postgres -d vrops -f migrate_insert_permissions.sql

GRANT INSERT ON trainees, sessions, session_steps TO vrops_api;
GRANT USAGE, SELECT ON SEQUENCE trainees_id_seq, sessions_id_seq, session_steps_id_seq TO vrops_api;
