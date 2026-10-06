-- Approval rate must be a proportion between 0 and 1.
select txn_date
from {{ ref('mart_daily_kpis') }}
where approval_rate < 0 or approval_rate > 1
