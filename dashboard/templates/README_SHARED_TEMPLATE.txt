SHARED BATTER + BOWLER STATS TEMPLATE
======================================

Both dashboards now use: templates/stats.html

Routes:
- /batters -> stats.html with dashboard_type="batter"
- /bowlers -> stats.html with dashboard_type="bowler"

The Flask route passes the dashboard type and page-specific presentation values.
The shared Jinja template uses conditional blocks only where the two dashboards
have genuinely different content (KPIs, labels, legends, matchup columns, sidebar
metrics, and page-specific actions).

For future common UI/layout changes, edit stats.html once and the change will
apply to both Batter Stats and Bowler Stats.
