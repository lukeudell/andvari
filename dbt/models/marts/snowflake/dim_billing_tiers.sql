select
    {{ dbt_utils.generate_surrogate_key(['tier_name']) }} as billing_tier_key,
    tier_name,
    monthly_price_usd,
    rate_limit_rpm,
    has_priority_access
from (
    values
        ('Free',       0.00,    60, false),
        ('Starter',   25.00,   300, false),
        ('Pro',      100.00,  1000, true),
        ('Enterprise', 500.00, 5000, true)
) as t(tier_name, monthly_price_usd, rate_limit_rpm, has_priority_access)
