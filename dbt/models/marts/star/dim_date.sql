with dates as (
    select * from {{ ref('stg_dates') }}
)

select
    date_key,
    full_date,
    day_of_week,
    is_weekend,
    week_of_year,
    month_name,
    quarter,
    year
from dates
