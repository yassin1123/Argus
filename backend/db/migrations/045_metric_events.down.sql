-- Down: drop the metric_events table + its indexes.
DROP INDEX IF EXISTS idx_metric_events_firm;
DROP INDEX IF EXISTS idx_metric_events_name_time;
DROP TABLE IF EXISTS metric_events;
