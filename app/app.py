"""Empty-trip analysis: one page over the dbt marts.

Run with ``uv run --group app streamlit run app/app.py`` after ``dbt build``.
The sliders change the scenario on the page only; the assumptions in
``dbt/seeds/cost_assumptions.csv`` stay the source of record.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import psycopg
import streamlit as st

st.set_page_config(page_title="Empty-trip analysis", layout="wide")


@st.cache_data(ttl=600)
def query(sql: str) -> pd.DataFrame:
    with psycopg.connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def eur(x: float) -> str:
    if abs(x) >= 1e6:
        return f"EUR {x / 1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"EUR {x / 1e3:,.0f}k"
    return f"EUR {x:,.0f}"


s = query("select * from marts.mart_savings_scenario").iloc[0].astype(float)
monthly = query("select * from marts.agg_empty_km_monthly order by month")
trucks = query("select * from marts.agg_empty_km_by_truck order by empty_km_share desc")
bands = query(
    "select distance_band, count(*) as empty_trips, sum(km) as empty_km "
    "from marts.fct_empty_trips group by distance_band"
)
starts = query(
    "select start_lat as lat, start_lon as lon from marts.fct_empty_trips where km >= 150"
)

st.title("Empty-trip analysis")
st.caption(
    f"{int(s.trucks)} trucks, {int(s.period_days)} days of synthetic GPS and cargo events. "
    "An empty trip is a leg between an unload and the next load, run without cargo, "
    "of at least 5 km."
)

c = st.columns(4)
c[0].metric("Empty trips a year", f"{s.empty_trips_per_year:,.0f}")
c[1].metric("Share of km run empty", f"{s.empty_km_share:.1%}")
c[2].metric("Cost per empty km", f"EUR {s.cost_per_empty_km:.2f}")
c[3].metric("Annual cost of empty running", eur(s.annual_empty_cost))

st.subheader("Scenario")
left, right = st.columns([1, 2])
with left:
    reduction = st.slider(
        "Cut empty km by", 0.0, 0.6, float(s.reduction_share), 0.05, format="%.2f"
    )
    detour = st.slider(
        "Detour km per avoided km", 0.0, 0.6, float(s.detour_share), 0.05, format="%.2f"
    )
    cost_km = st.slider(
        "Cost per empty km (EUR)",
        0.6,
        1.8,
        round(float(s.cost_per_empty_km), 3),
        0.001,
        format="%.3f",
    )
    programme = st.slider(
        "Programme cost per truck a year (EUR)", 0, 5000, int(s.programme_cost / s.trucks), 100
    )
avoided = s.annual_empty_km * reduction
gross = avoided * cost_km
detour_cost = avoided * detour * cost_km
programme_cost = programme * s.trucks
net = gross - detour_cost - programme_cost
with right:
    k = st.columns(4)
    k[0].metric("Gross saving", eur(gross))
    k[1].metric("Detour km", eur(-detour_cost))
    k[2].metric("Programme", eur(-programme_cost))
    k[3].metric("Net saving a year", eur(net))
    steps = pd.DataFrame(
        {
            "step": ["Gross saving", "Detour km", "Programme", "Net saving"],
            "EUR": [gross, -detour_cost, -programme_cost, net],
        }
    )
    st.altair_chart(
        alt.Chart(steps)
        .mark_bar()
        .encode(
            x=alt.X("step:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("EUR:Q", title="EUR a year", axis=alt.Axis(format="~s")),
            color=alt.condition(alt.datum.EUR < 0, alt.value("#d9534f"), alt.value("#4c78a8")),
            tooltip=[alt.Tooltip("EUR:Q", format=",.0f")],
        )
        .properties(height=240),
        width="stretch",
    )

st.subheader("Where the empty km come from")
a, b = st.columns(2)
with a:
    st.markdown("**Share of km run empty, by month**")
    st.altair_chart(
        alt.Chart(monthly)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:T", title=None),
            y=alt.Y(
                "empty_km_share:Q",
                title="Empty share",
                axis=alt.Axis(format="%"),
                scale=alt.Scale(zero=True),
            ),
            tooltip=[alt.Tooltip("month:T"), alt.Tooltip("empty_km_share:Q", format=".1%")],
        )
        .properties(height=260),
        width="stretch",
    )
with b:
    st.markdown("**Empty trips and empty km, by trip length**")
    order = ["5-50 km", "50-150 km", "150-300 km", "300+ km"]
    shares = bands.assign(
        trips=bands.empty_trips / bands.empty_trips.sum(), km=bands.empty_km / bands.empty_km.sum()
    ).melt(id_vars="distance_band", value_vars=["trips", "km"], var_name="measure")
    shares["measure"] = shares.measure.map({"trips": "share of trips", "km": "share of km"})
    st.altair_chart(
        alt.Chart(shares)
        .mark_bar()
        .encode(
            x=alt.X("distance_band:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            xOffset="measure:N",
            y=alt.Y("value:Q", title=None, axis=alt.Axis(format="%")),
            color=alt.Color("measure:N", title=None, legend=alt.Legend(orient="top")),
            tooltip=["distance_band", "measure", alt.Tooltip("value:Q", format=".1%")],
        )
        .properties(height=260),
        width="stretch",
    )
    st.caption(
        "Most empty trips are short hops across town; most empty km come from the long "
        "repositioning runs. That is where backhaul loads pay."
    )

a, b = st.columns(2)
with a:
    st.markdown("**Trucks with the highest empty share**")
    top = trucks.head(15)[["truck_id", "home_depot", "empty_trips", "empty_km", "empty_km_share"]]
    st.dataframe(
        top.assign(empty_km_share=top.empty_km_share.astype(float) * 100),
        hide_index=True,
        column_config={
            "empty_km": st.column_config.NumberColumn("empty km", format="%.0f"),
            "empty_km_share": st.column_config.NumberColumn("empty share", format="%.1f %%"),
        },
    )
with b:
    st.markdown("**Where long empty runs (150 km+) start**")
    st.map(starts, size=2000)
