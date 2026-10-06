-- Business rule: fraud losses only exist on approved payments.
-- A declined or reversed payment flagged as fraud means a data problem upstream.
select txn_id
from {{ ref('fct_transactions') }}
where is_fraud = 1
  and status <> 'APPROVED'
