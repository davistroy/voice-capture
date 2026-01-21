# Week of {{ start_date }} - {{ end_date }}

## Overview
{{ overview }}

## Accomplishments
{% for item in accomplishments %}
- {{ item }}
{% endfor %}
{% if not accomplishments %}
*No accomplishments captured this week*
{% endif %}

## Key Activities
{{ key_activities }}

## Challenges & Blockers
{% for item in challenges %}
- {{ item }}
{% endfor %}
{% if not challenges %}
*No challenges noted this week*
{% endif %}

## Ideas Generated
{% for idea in ideas %}
- [{{ idea.title }}]({{ idea.url }}){% if idea.summary %}: {{ idea.summary }}{% endif %}

{% endfor %}
{% if not ideas %}
*No ideas captured this week*
{% endif %}

## Insights & Reflections
{{ insights }}

## Upcoming / Next Week
{% for item in upcoming %}
- {{ item }}
{% endfor %}
{% if not upcoming %}
*No upcoming items identified*
{% endif %}

## Capture Statistics
- **Total captures:** {{ stats.total_captures }}
- **By type:** {% for type, count in stats.by_type.items() %}{{ type }}({{ count }}){% if not loop.last %}, {% endif %}{% endfor %}

- **Total recording time:** {{ stats.total_duration_formatted }}
- **Date range:** {{ start_date }} to {{ end_date }}

---
*Generated from {{ stats.total_captures }} voice capture{% if stats.total_captures != 1 %}s{% endif %}{% if stats.supplemental_input_used %} (includes supplemental input){% endif %}*
