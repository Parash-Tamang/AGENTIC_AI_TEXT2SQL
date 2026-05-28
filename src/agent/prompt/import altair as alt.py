import altair as alt
from vega_datasets import data

stocks = data.stocks()

chart = (
    alt.Chart(stocks)
    .mark_bar()
    .encode(x="date:T", y="price:Q", color="symbol:N")
    .properties(width=700, height=400, title="Stock Prices Over Time")
)

# Save as PNG
chart.save("stocks_chart.svg")
