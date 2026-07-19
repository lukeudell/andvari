select
    s.date_key
    , s.full_date
    , s.day_of_week
    , s.is_weekend
    , s.week_of_year
    , s.month_name
    , s.quarter
    , s.year
from {{ source('raw_staging', 'dates') }} as s
