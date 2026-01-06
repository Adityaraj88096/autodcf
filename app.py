import pandas as pd
import yfinance as yf
import streamlit as st
import numpy as np
from io import BytesIO

st.set_page_config(page_title="Auto DCF v1", layout="centered")
st.title = "Auto Dcf v1"

#Code for sidebar
rf= 6 #Riskfree rate
rp = 5 #Risk premiumawe
with st.sidebar:
    st.header("Model Assumptions")
    ticker = st.text_input("Ticker (NSE add .NS)", "ITC.NS").upper().strip()
    forecast_years = st.slider("Forecast years", 3, 10, 5)
    growth = st.number_input("FCF Growth(next phase %)", 0.0, 50.0, 12.0, 0.5)/100
    terminal = st.number_input("Terminal growth rate", 0.0, 10.0, 5.00, 0.25 )/100
    wacc = st.number_input("WACC", 0.0, 50.0,10.0, 0.25)/100
st.write("Value of Ticker", ticker)
st.markdown("---")
export_excel = st.button("📥 Export Excel")

@st.cache_data(show_spinner=False)
def get_data(tic):
    try:
        stk = yf.Ticker(tic)
        info = stk.info
        fin = stk.financials
        bs = stk.balance_sheet
        cf = stk.cashflow
        return info, fin, bs, cf
    except Exception as e:
        return None, None, None, None
    
info, fin, bs, cf = get_data(ticker)
if info is None: 
    st.error("Could not fetch data - check ticker or internet connection")
    st.stop()

def get_fcf_series(cf):
    """Return series of FCF in local currency"""
    ocf = cf.loc["Operating Cash Flow"]
    capex = cf.loc["Capital Expenditure"]
    fcf = (ocf + capex).dropna()  #Capex is negative, so + sign as - sign will alter the signs
    return fcf

def dcf_model(fcf0, fy, g, t, w):
    """Return Dataframe of projections and valuation components."""
    proj = [fcf0*(1+g)**(i+1) for i in range(fy)]
    terminal_value = proj[-1]*(1+t)/(w-t)
    pv_proj = [proj[i]/(1+w)**(i+1) for i in range(fy)]
    pv_term = terminal_value/(1+w)**fy
    ent_val = sum(pv_proj) + pv_term
    return pd.DataFrame({
        "Year":  list(range(1, fy+1)) + ["Terminal"],
        "FCF":    proj + [terminal_value],
        "PV":       [round(pv_proj[i],0) for i in range(fy)] + [round(pv_term, 0)]
    }), ent_val

# MODEL
fcf_series = get_fcf_series(cf)
if fcf_series.empty or fcf_series.iloc[0] <= 0:
    st.warning("FCF missing or negative - model may be unreliable")
    st.stop()

last_fcf = fcf_series.iloc[0]
proj_df, ev = dcf_model(last_fcf, forecast_years, growth, terminal, wacc)
proj_df["Year"] = proj_df["Year"].astype(str)
net_debt = info.get("totalDebt", 0) - info.get("cash", 0)
shares = info.get("sharesOutstanding", 1)
equity_val = ev - net_debt
fair_value = equity_val/shares
curr_price = info.get("currentPrice", np.nan)
upside = (fair_value/curr_price - 1) if curr_price else np.nan


# METRICS
c1, c2, c3 = st.columns(3)
c1.metric("EV (Rs. Cr)", f"{(ev/10000000):,.0f}")
c2.metric("Equity Vale (Rs. Cr)", f"{(equity_val/10000000):,.0f}")
c3.metric("Fair Value/ share(Rs.)", f"{fair_value:,.0f}")
if not pd.isna(upside):
    c3.metric("Upside %", f"{upside:.1%}")

# SENSITIVITY
st.subheader("Sensitivity – Fair Value vs. Growth & WACC")
heat_g = np.linspace(growth*0.6, growth*1.4, 7)
heat_w = np.linspace(wacc*0.8, wacc*1.2, 7)
sens_table = np.array([[dcf_model(last_fcf, forecast_years, g, terminal, w)[1] - net_debt
                       for w in heat_w] for g in heat_g])
sens_df = pd.DataFrame(sens_table/shares, columns=[f"{w:.1%}" for w in heat_w],
                       index=[f"{g:.1%}" for g in heat_g])
st.dataframe(sens_df.style.background_gradient(cmap="RdYlGn"), width='stretch')


# Details
with st.expander("See yearly Projections"):
    st.dataframe(proj_df)


#Excel export
if export_excel:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        proj_df.to_excel(writer, sheet_name="Projections", index=False)
        pd.DataFrame({
            "Metric": ["EV", "Net Debt", "Equity Value", "Shares", "Fair Value", "Current Price", "Upside"],
            "₹ Cr / per share": [ev, net_debt, equity_val, shares, fair_value,
                                  curr_price if not pd.isna(curr_price) else "NA",
                                  f"{upside:.1%}" if not pd.isna(upside) else "NA"]
        }).to_excel(writer, sheet_name="Summary", index=False)
    buffer.seek(0)
    st.sidebar.download_button(label="📥 Download", data=buffer,
                               file_name=f"{ticker}_DCF.xlsx", mime="application/vnd.ms-excel")