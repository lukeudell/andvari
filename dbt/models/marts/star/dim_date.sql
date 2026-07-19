select
    d.date_key
    , d.full_date
    , d.day_of_week
    , d.is_weekend
    , d.week_of_year
    , d.month_name
    , d.quarter
    , d.year
from {{ ref('stg_dates') }} as d
