ROLES = ('admin', 'operator', 'viewer')
DRILL_STATUSES = ('queued', 'running', 'completed', 'failed')
PURGE_STATUSES = ('queued', 'running', 'completed', 'failed')
# Ordered cleanup units. Each unit is committed on its own so an interrupted
# purge can resume from the next uncommitted unit.
PURGE_STEPS = ('redact_logs', 'redact_snapshots', 'redact_results')
