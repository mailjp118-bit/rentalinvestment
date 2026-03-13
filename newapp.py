import streamlit as st
import requests
import pandas as pd
import math
from typing import Dict, Any

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(page_title="Rental Investment Analyzer", layout="wide")

# ============================================================
# CONSTANTS
# ============================================================
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
CENSUS_ACS_URL = "https://api.census.gov/data/2023/acs/acs5"

# ============================================================
# HELPERS
# ============================================================
def safe_float(value, default=0.0):
    try:
        if value in [None, "", "null"]:
            return default
        return float(str(value).replace(",", "").replace("$", "").strip())
    except Exception:
        return default


def monthly_mortgage_payment(loan_amount: float, annual_rate: float, years: int = 30) -> float:
    monthly_rate = annual_rate / 12 / 100
    n = years * 12

    if loan_amount <= 0:
        return 0.0
    if monthly_rate == 0:
        return loan_amount / n

    return loan_amount * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)


def get_verdict(cash_flow: float) -> str:
    if cash_flow >= 200:
        return "Good Deal"
    elif cash_flow >= 0:
        return "Borderline Deal"
    return "Bad Deal"


# ============================================================
# API FUNCTIONS
# ============================================================
def get_census_geo(address: str) -> Dict[str, Any]:
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Census Tracts",
        "format": "json",
    }

    try:
        r = requests.get(CENSUS_GEOCODER_URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        matches = data.get("result", {}).get("addressMatches", [])
        if not matches:
            return {"success": False, "error": "No geocoder match found."}

        geo = matches[0]
        geos = geo.get("geographies", {})
        tracts = geos.get("Census Tracts", [])

        if not tracts:
            return {"success": False, "error": "No census tract found."}

        tract = tracts[0]

        return {
            "success": True,
            "matched_address": geo.get("matchedAddress"),
            "state_fips": tract.get("STATE"),
            "county_fips": tract.get("COUNTY"),
            "tract_code": tract.get("TRACT"),
            "county_name": tract.get("COUNTYNAME"),
            "state_name": tract.get("STATENAME"),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_household_income(state_fips: str, county_fips: str, tract_code: str) -> Dict[str, Any]:
    params = {
        "get": "NAME,B19013_001E",
        "for": f"tract:{tract_code}",
        "in": f"state:{state_fips} county:{county_fips}",
    }

    try:
        r = requests.get(CENSUS_ACS_URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        if len(data) < 2:
            return {"success": False, "error": "Income data not found."}

        row = data[1]
        return {
            "success": True,
            "name": row[0],
            "median_household_income": safe_float(row[1], 0.0),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# OPTIONAL PLACEHOLDER FETCHERS
# These do not break the app if websites block scraping
# ============================================================
def try_fetch_rent_placeholder(address: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": "Automatic rent fetch not configured. Enter rent manually."
    }


def try_fetch_school_placeholder(address: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": "Automatic school fetch not configured. Enter school info manually."
    }


def try_fetch_crime_placeholder(address: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": "Automatic crime fetch not configured. Enter crime note manually."
    }


def try_fetch_retainability_placeholder(address: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": "Automatic renter retainability fetch not configured. Enter note manually."
    }


# ============================================================
# CALCULATIONS
# ============================================================
def calculate_rental_metrics(
    purchase_price: float,
    down_payment_pct: float,
    interest_rate: float,
    property_tax_annual: float,
    insurance_annual: float,
    hoa_monthly: float,
    estimated_rent: float,
    maintenance_pct: float = 10.0,
    vacancy_pct: float = 10.0,
):
    down_payment = purchase_price * (down_payment_pct / 100)
    loan_amount = purchase_price - down_payment

    mortgage_pi = monthly_mortgage_payment(loan_amount, interest_rate, years=30)
    tax_monthly = property_tax_annual / 12
    insurance_monthly = insurance_annual / 12
    maintenance_monthly = estimated_rent * (maintenance_pct / 100)
    vacancy_monthly = estimated_rent * (vacancy_pct / 100)

    total_monthly_cost = (
        mortgage_pi
        + tax_monthly
        + insurance_monthly
        + hoa_monthly
        + maintenance_monthly
        + vacancy_monthly
    )

    cash_flow = estimated_rent - total_monthly_cost

    return {
        "down_payment": down_payment,
        "loan_amount": loan_amount,
        "mortgage_pi": mortgage_pi,
        "tax_monthly": tax_monthly,
        "insurance_monthly": insurance_monthly,
        "hoa_monthly": hoa_monthly,
        "maintenance_monthly": maintenance_monthly,
        "vacancy_monthly": vacancy_monthly,
        "total_monthly_cost": total_monthly_cost,
        "estimated_rent": estimated_rent,
        "cash_flow": cash_flow,
    }


# ============================================================
# SESSION STATE DEFAULTS
# ============================================================
default_values = {
    "geo": {},
    "income": {},
    "rent_fetch": {},
    "school_fetch": {},
    "crime_fetch": {},
    "retain_fetch": {},
}

for key, value in default_values.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ============================================================
# TOP BAR
# ============================================================
top_left, top_middle, top_right = st.columns([5, 2, 2])

with top_left:
    st.title("🏠 Rental Investment Analyzer")

with top_middle:
    st.markdown("###")
    st.caption("Hybrid API + Manual Input")

with top_right:
    st.markdown("###")
    st.caption("More reliable than scraping-only")

# ============================================================
# PRIVACY MESSAGE
# ============================================================
st.markdown(
    """
    🔒 **Privacy Notice:**  
    *This tool does not depend on scraping every site to work. Reliable data is fetched by API where possible, and missing items can be entered manually.*
    """
)

# ============================================================
# MAIN LAYOUT
# ============================================================
left_col, mid_col, right_col = st.columns([1.15, 1, 1])

# ============================================================
# LEFT COLUMN - INPUTS
# ============================================================
with left_col:
    st.subheader("🔢 Deal Inputs")

    address = st.text_area(
        "Property Address",
        value="1394 Stephens Pond Vw, Loganville, GA 30052",
        height=70
    )

    purchase_price = st.number_input("Purchase Price ($)", min_value=0.0, value=310000.0, step=1000.0)
    down_payment_pct = st.number_input("Down Payment (%)", min_value=0.0, max_value=100.0, value=30.0, step=1.0)
    interest_rate = st.number_input("Interest Rate (%)", min_value=0.0, value=6.75, step=0.1)

    property_tax_annual = st.number_input("Annual Property Tax ($)", min_value=0.0, value=3576.0, step=100.0)
    insurance_annual = st.number_input("Annual Insurance ($)", min_value=0.0, value=1584.0, step=100.0)
    hoa_monthly = st.number_input("HOA Monthly ($)", min_value=0.0, value=38.0, step=5.0)

    estimated_rent = st.number_input("Estimated Monthly Rent ($)", min_value=0.0, value=2059.0, step=50.0)

    st.subheader("📝 Manual Notes / Optional Inputs")
    elementary_school = st.text_input("Elementary School", value="Magill Elementary")
    school_rating = st.text_input("School Rating", value="")
    crime_note = st.text_input("Crime Note", value="")
    retainability_note = st.text_input("Renter Retainability", value="")
    time_to_rent = st.text_input("Time to Rent", value="")

    st.subheader("🌐 Fetch Tools")

    if st.button("Fetch Census Geography + Household Income", use_container_width=True):
        geo = get_census_geo(address)
        st.session_state["geo"] = geo

        if geo.get("success"):
            income = get_household_income(
                geo["state_fips"],
                geo["county_fips"],
                geo["tract_code"]
            )
            st.session_state["income"] = income
        else:
            st.session_state["income"] = {"success": False, "error": "Skipped because geocoding failed."}

    if st.button("Try Fetch Rent", use_container_width=True):
        st.session_state["rent_fetch"] = try_fetch_rent_placeholder(address)

    if st.button("Try Fetch School Info", use_container_width=True):
        st.session_state["school_fetch"] = try_fetch_school_placeholder(address)

    if st.button("Try Fetch Crime", use_container_width=True):
        st.session_state["crime_fetch"] = try_fetch_crime_placeholder(address)

    if st.button("Try Fetch Retainability", use_container_width=True):
        st.session_state["retain_fetch"] = try_fetch_retainability_placeholder(address)

# ============================================================
# CALCULATIONS
# ============================================================
metrics = calculate_rental_metrics(
    purchase_price=purchase_price,
    down_payment_pct=down_payment_pct,
    interest_rate=interest_rate,
    property_tax_annual=property_tax_annual,
    insurance_annual=insurance_annual,
    hoa_monthly=hoa_monthly,
    estimated_rent=estimated_rent,
)

verdict = get_verdict(metrics["cash_flow"])
income_value = st.session_state.get("income", {}).get("median_household_income", None)
geo = st.session_state.get("geo", {})
income = st.session_state.get("income", {})
rent_fetch = st.session_state.get("rent_fetch", {})
school_fetch = st.session_state.get("school_fetch", {})
crime_fetch = st.session_state.get("crime_fetch", {})
retain_fetch = st.session_state.get("retain_fetch", {})

# ============================================================
# MIDDLE COLUMN - PROPERTY DETAILS + RENT VS EXPENSES
# ============================================================
with mid_col:
    st.subheader("📋 Property Details")

    details_df = pd.DataFrame({
        "Category": [
            "Property Address",
            "Estimated Purchase Price",
            "Down Payment",
            "Loan Amount",
            "Elementary School",
            "GreatSchools Rating",
            "Crime Note",
            "Renter Retainability",
            "Median Household Income",
            "Time to Rent",
        ],
        "Data / Estimate": [
            address,
            f"${purchase_price:,.0f}",
            f"${metrics['down_payment']:,.0f}",
            f"${metrics['loan_amount']:,.0f}",
            elementary_school if elementary_school else "Not entered",
            school_rating if school_rating else "Not entered",
            crime_note if crime_note else "Not entered",
            retainability_note if retainability_note else "Not entered",
            f"${income_value:,.0f}" if income_value else "Not fetched",
            time_to_rent if time_to_rent else "Not entered",
        ]
    })

    st.table(details_df)

    st.subheader("💵 Rent vs Expenses")

    rent_vs_expenses_df = pd.DataFrame({
        "Metric": [
            "Estimated Monthly Rent",
            "Total Monthly Expenses",
            "Estimated Cash Flow",
        ],
        "Amount": [
            f"${metrics['estimated_rent']:,.0f}",
            f"${metrics['total_monthly_cost']:,.0f}",
            f"${metrics['cash_flow']:,.0f}",
        ]
    })

    st.table(rent_vs_expenses_df)

# ============================================================
# RIGHT COLUMN - MONTHLY PAYMENT + VERDICT + FETCH STATUS
# ============================================================
with right_col:
    st.subheader("🏦 Monthly Payment Estimate")

    monthly_df = pd.DataFrame({
        "Expense": [
            "Mortgage (Principal + Interest)",
            "Property Tax",
            "Insurance",
            "HOA",
            "Maintenance (10% of Rent)",
            "Vacancy (10% of Rent)",
            "Total Monthly Cost",
        ],
        "Monthly Cost": [
            f"${metrics['mortgage_pi']:,.0f}",
            f"${metrics['tax_monthly']:,.0f}",
            f"${metrics['insurance_monthly']:,.0f}",
            f"${metrics['hoa_monthly']:,.0f}",
            f"${metrics['maintenance_monthly']:,.0f}",
            f"${metrics['vacancy_monthly']:,.0f}",
            f"${metrics['total_monthly_cost']:,.0f}",
        ]
    })

    st.table(monthly_df)

    st.subheader("✅ Investment Verdict")

    verdict_df = pd.DataFrame({
        "Factor": [
            "Cash Flow",
            "Overall Rental Deal",
        ],
        "Rating": [
            "Positive" if metrics["cash_flow"] >= 0 else "Negative",
            verdict,
        ]
    })

    st.table(verdict_df)

    st.subheader("🔎 Fetch Status")

    status_rows = []

    if geo:
        if geo.get("success"):
            status_rows.append(["Census Geography", "Success"])
        else:
            status_rows.append(["Census Geography", f"Failed: {geo.get('error', 'Unknown error')}"])

    if income:
        if income.get("success"):
            status_rows.append(["Household Income", "Success"])
        else:
            status_rows.append(["Household Income", f"Failed: {income.get('error', 'Unknown error')}"])

    if rent_fetch:
        if rent_fetch.get("success"):
            status_rows.append(["Rent Fetch", "Success"])
        else:
            status_rows.append(["Rent Fetch", rent_fetch.get("error", "Failed")])

    if school_fetch:
        if school_fetch.get("success"):
            status_rows.append(["School Fetch", "Success"])
        else:
            status_rows.append(["School Fetch", school_fetch.get("error", "Failed")])

    if crime_fetch:
        if crime_fetch.get("success"):
            status_rows.append(["Crime Fetch", "Success"])
        else:
            status_rows.append(["Crime Fetch", crime_fetch.get("error", "Failed")])

    if retain_fetch:
        if retain_fetch.get("success"):
            status_rows.append(["Retainability Fetch", "Success"])
        else:
            status_rows.append(["Retainability Fetch", retain_fetch.get("error", "Failed")])

    if status_rows:
        status_df = pd.DataFrame(status_rows, columns=["Source", "Status"])
        st.table(status_df)
    else:
        st.info("No fetches run yet.")

# ============================================================
# SUMMARY METRICS
# ============================================================
st.markdown("---")
m1, m2, m3, m4 = st.columns(4)

m1.metric("Estimated Rent", f"${metrics['estimated_rent']:,.0f}")
m2.metric("Monthly Cost", f"${metrics['total_monthly_cost']:,.0f}")
m3.metric("Cash Flow", f"${metrics['cash_flow']:,.0f}")
m4.metric("Verdict", verdict)
