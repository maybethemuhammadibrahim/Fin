"""[B] Plotly cash-flow projection: baseline vs recovered. Phase 9.

**Phase 2 builds the chart; Phase 9 supplies real projections.** The component
takes two already-computed series and draws them. It does no arithmetic beyond
formatting — the cumulative maths that produces the series belongs in
`core/engine/cashflow.py`, which is a Phase 9 stub.

Today's caller derives both series from seeded database rows, so every point on
the chart still traces to a row (ADR-008). Nothing here is a hardcoded figure.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

BASELINE_COLOUR = "#8899a6"
RECOVERED_COLOUR = "#00c48c"
HIRE_COLOUR = "#ff4b4b"


def render_cash_flow_chart(
    baseline: list[float],
    recovered: list[float],
    labels: list[str] | None = None,
    threshold: float | None = None,
    threshold_label: str = "Cost of the hire",
) -> None:
    """Two cumulative cash lines, optionally against a cost threshold.

    `baseline` is cash without recovering the leaks; `recovered` is with. An
    optional `threshold` draws the commitment being considered, so the gap
    between the lines can be read against it.
    """
    if not baseline or not recovered:
        st.caption("Not enough data to project.")
        return

    x = labels or [f"M{i + 1}" for i in range(len(baseline))]

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=x, y=baseline, name="Without recovery", mode="lines+markers",
            line=dict(color=BASELINE_COLOUR, width=2, dash="dot"),
            hovertemplate="%{x}<br>$%{y:,.0f}<extra>Without recovery</extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=x, y=recovered, name="With recovered revenue", mode="lines+markers",
            line=dict(color=RECOVERED_COLOUR, width=3),
            fill="tonexty", fillcolor="rgba(0,196,140,0.12)",
            hovertemplate="%{x}<br>$%{y:,.0f}<extra>With recovery</extra>",
        )
    )

    if threshold is not None:
        figure.add_hline(
            y=threshold,
            line=dict(color=HIRE_COLOUR, width=2, dash="dash"),
            annotation_text=threshold_label,
            annotation_position="top left",
        )

    figure.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(title="Cumulative cash", tickformat="$,.0f"),
        xaxis=dict(title=None),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    st.plotly_chart(figure, use_container_width=True)


def render_breakdown(rows: list[tuple[str, float]]) -> None:
    """A small label/amount table under the chart. Amounts are pre-computed."""
    if not rows:
        return
    st.dataframe(
        [{"Line": label, "Amount": amount} for label, amount in rows],
        hide_index=True,
        use_container_width=True,
        column_config={"Amount": st.column_config.NumberColumn(format="$%.0f")},
    )
