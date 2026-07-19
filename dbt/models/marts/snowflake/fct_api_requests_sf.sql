with requests as (
    select * from {{ ref('stg_api_requests') }}
),

dim_users_sf as (
    select * from {{ ref('dim_users_sf') }}
),

dim_models as (
    select * from {{ ref('dim_models') }}
),

dim_endpoints as (
    select * from {{ ref('dim_endpoints') }}
),

dim_date as (
    select * from {{ ref('dim_date') }}
)

select
    requests.request_id,
    dim_users_sf.user_key,
    dim_models.model_key,
    dim_date.date_key,
    dim_endpoints.endpoint_key,
    requests.latency_ms,
    requests.tokens_input,
    requests.tokens_output,
    requests.tokens_total,
    requests.cost_usd,
    requests.http_status,
    requests.safety_flag,
    requests.request_timestamp
from requests
inner join dim_users_sf
    on requests.user_id = dim_users_sf.user_id
inner join dim_models
    on requests.model_id = dim_models.model_id
inner join dim_date
    on cast(to_char(requests.request_timestamp, 'YYYYMMDD') as integer) = dim_date.date_key
inner join dim_endpoints
    on requests.endpoint_path = dim_endpoints.endpoint_path
