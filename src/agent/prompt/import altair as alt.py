import altair as alt
import pandas as pd

df = pd.DataFrame(
    {
        "Category": ["Health", "Roads", "Power", "Education"],
        "Revenue": [1200, 900, 600, 300],
    }
)

chart = (
    alt.Chart(df)
    .mark_arc()
    .encode(
        theta=alt.Theta("Revenue:Q"),
        color=alt.Color("Category:N"),
        tooltip=["Category", "Revenue"],
    )
    .properties(width=500, height=400, title="Revenue by Category")
)

chart.save("pie_chart.png")
