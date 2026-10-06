-- Every transaction must have a positive USD amount.
select txn_id
from {{ ref('fct_transactions') }}
where amount_usd <= 0
