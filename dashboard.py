import streamlit as st
import pandas as pd
import os
from sqlalchemy import create_engine, text

# Page configuration
st.set_page_config(page_title="BiasharaForce Dashboard", page_icon="📈", layout="wide")
st.title("📈 BiasharaForce Business Dashboard")
st.markdown("Real-time analytics from your WhatsApp & Voice Accounting Agent")

# Refresh Button
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# Connect to Supabase Postgres Database
DATABASE_URL = os.getenv("DATABASE_URL")

# Fallback for Streamlit Community Cloud Secrets
if not DATABASE_URL:
    try:
        DATABASE_URL = st.secrets["DATABASE_URL"]
    except:
        st.error("🚨 DATABASE_URL is missing! Please add it to Streamlit Secrets.")
        st.stop()

# Render/SQLAlchemy requires "postgresql://" instead of "postgres://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

@st.cache_resource
def get_connection():
    return create_engine(DATABASE_URL)

engine = get_connection()

# Load data
@st.cache_data(ttl=10) # Auto-refresh every 10 seconds
def load_data():
    with engine.connect() as conn:
        df = pd.read_sql_query(text("SELECT * FROM transactions ORDER BY timestamp DESC"), conn)
    return df

df = load_data()

# SIDEBAR FILTERS
st.sidebar.header("Filters")
if not df.empty:
    df['reason'] = df['reason'].fillna("Unknown")
    reasons = df['reason'].unique().tolist()
    selected_reasons = st.sidebar.multiselect("Filter by Reason", reasons, default=reasons)
    filtered_df = df[df['reason'].isin(selected_reasons)]
else:
    filtered_df = df

# TOP METRICS
col1, col2, col3 = st.columns(3)

with col1:
    total_revenue = filtered_df['amount'].sum()
    st.metric(label="Total Revenue (Ksh)", value=f"{total_revenue:,.2f}")

with col2:
    total_tax = filtered_df['tax_amount'].sum()
    st.metric(label="Total Tax Withheld (Ksh)", value=f"{total_tax:,.2f}")

with col3:
    total_transactions = len(filtered_df)
    st.metric(label="Total Transactions", value=total_transactions)

st.divider()

# CHARTS
if not filtered_df.empty:
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.subheader("Revenue by Category")
        chart_data = filtered_df.groupby('reason')['amount'].sum().sort_values(ascending=False)
        st.bar_chart(chart_data)
        
    with col_chart2:
        st.subheader("Tax vs Net Revenue")
        net_revenue = total_revenue - total_tax
        pie_data = pd.DataFrame({'Amount': [net_revenue, total_tax]}, index=['Net Revenue', 'Tax Withheld'])
        st.bar_chart(pie_data)
else:
    st.info("No data matching filters.")

st.divider()

# DATA TABLE & EXPORT
st.subheader("Recent Transactions")

cols_to_show = ['timestamp', 'sender_name', 'sender_phone', 'reason', 'amount', 'tax_amount']
existing_cols = [col for col in cols_to_show if col in filtered_df.columns]

display_df = filtered_df[existing_cols].copy()

rename_dict = {
    'timestamp': 'Date & Time',
    'sender_name': 'Customer',
    'sender_phone': 'Phone Number',
    'reason': 'Reason',
    'amount': 'Amount (Ksh)',
    'tax_amount': 'Tax (Ksh)'
}
display_df.rename(columns=rename_dict, inplace=True)

st.dataframe(display_df, width="stretch", hide_index=True)

if not display_df.empty:
    csv = display_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Data as CSV",
        data=csv,
        file_name='biasharaforce_transactions.csv',
        mime='text/csv',
    )