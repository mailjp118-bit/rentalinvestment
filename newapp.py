import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import math
import re
import json
from urllib.parse import quote_plus

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
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# ============================================================
# HELPERS
# ============================================================
def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
        return float(cleaned)
    except Exception:
        return default


def fmt_money(x):
    try:
        return f"${x:,.0f}"
    except Exception:
        return "$0"


def fmt_pct(x):
    try:
        return f"{x:.1f}%"
    except Exception:
        return "0.0%"


def monthly_mortgage_payment(loan_amount, annual_rate, years):
    """
    Standard amortizing mortgage formula.
    """
    if loan_amount <= 0:
        return 0.0
    r = annual_rate / 12 / 100
    n = years * 12
    if r == 0:
        return loan_amount / n
    return loan_amount * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def fetch_url(url, params=None, timeout=20):
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def fetch_json(url, params=None, timeout=20):
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def regex_money_from_text(text, patterns):
    if not text:
        return None
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            raw = match.group(1)
            raw = raw.replace(",", "").replace("$", "").strip()
            try:
                return float(raw)
            except Exception:
                pass
    return None


def geocode_address_nominatim(address):
    params = {
        "q": address,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
    }
    data = fetch_json(NOMINATIM_URL, params=params, timeout=20)
    if not data:
        return {}

    row = data[0]
    address_info = row.get("address", {})

    return {
        "lat": safe_float(row.get("lat")),
        "lon": safe_float(row.get("lon")),
        "display_name": row.get("display_name", ""),
        "city": (
            address_info.get("city")
            or address_info.get("town")
            or address_info.get("village")
            or address_info.get("hamlet")
            or address_info.get("county")
            or ""
        ),
        "county": address_info.get("county", ""),
        "state": address_info.get("state", ""),
        "postcode": address_info.get("postcode", ""),
    }


def get_census_tract_and_income(address):
    """
    Uses Census geocoder + ACS 5-year median household income.
    """
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    geo = fetch_json(CENSUS_GEOCODER_URL, params=params, timeout=20)

    if not geo:
        return {}

    try:
        matches = geo["result"]["addressMatches"]
        if not matches:
            return {}
        geographies = matches[0]["geographies"]["Census Tracts"][0]

        state_fips = geographies["STATE"]
        county_fips = geographies["COUNTY"]
        tract_fips = geographies["TRACT"]

        income_params = {
            "get": "NAME,B19013_001E",
            "for": f"tract:{tract_fips}",
            "in": f"state:{state_fips} county:{county_fips}",
        }
        income_data = fetch_json(CENSUS_ACS_URL, params=income_params, timeout=20)

        median_income = None
        tract_name = None

        if income_data and len(income_data) > 1:
            headers = income_data[0]
            values = income_data[1]
            row = dict(zip(headers, values))
            tract_name = row.get("NAME")
            income_raw = row.get("B19013_001E")
            if income_raw not in (None, "-666666666", "-999999999"):
                median_income = safe_float(income_raw, None)

        return {
            "state_fips": state_fips,
            "county_fips": county_fips,
            "tract_fips": tract_fips,
            "tract_name": tract_name,
            "median_household_income": median_income,
        }
    except Exception:
        return {}


def extract_zillow_data(address):
    """
    Best effort only.
    Zillow may block this in some environments.
    """
    result = {
        "source": "Zillow",
        "search_url": f"https://www.zillow.com/homes/{quote_plus(address)}_rb/",
        "price": None,
        "rent_estimate": None,
        "property_tax_annual": None,
        "hoa_monthly": None,
        "status": "Not checked",
    }

    html = fetch_url(result["search_url"], timeout=20)
    if not html:
        result["status"] = "Unable to fetch Zillow page"
        return result

    # Try a few patterns often seen in Zillow HTML / JSON blobs
    price = regex_money_from_text(
        html,
        [
            r'"price"\s*:\s*"?\$?([\d,]+)"?',
            r'"unformattedPrice"\s*:\s*([\d,]+)',
            r'"priceValue"\s*:\s*([\d,]+)',
        ],
    )
    rent = regex_money_from_text(
        html,
        [
            r'"rentZestimate"\s*:\s*([\d,]+)',
            r'"rentEstimate"\s*:\s*([\d,]+)',
            r'"zestimateRentalPrice"\s*:\s*([\d,]+)',
        ],
    )
    hoa = regex_money_from_text(
        html,
        [
            r'"monthlyHoaFee"\s*:\s*([\d,]+)',
            r'"hoaFee"\s*:\s*"?\$?([\d,]+)"?',
        ],
    )

    # Property taxes are often harder to extract reliably from Zillow.
    tax = regex_money_from_text(
        html,
        [
            r'"taxAnnualAmount"\s*:\s*([\d,]+)',
            r'"annualTaxAmount"\s*:\s*([\d,]+)',
        ],
    )

    result["price"] = price
    result["rent_estimate"] = rent
    result["hoa_monthly"] = hoa
    result["property_tax_annual"] = tax
    result["status"] = "Fetched" if any([price, rent, hoa, tax]) else "Fetched page, no values parsed"
    return result


def extract_trulia_data(address):
    """
    Best effort only.
    Trulia frequently blocks automation.
    """
    result = {
        "source": "Trulia",
        "search_url": f"https://www.trulia.com/home/{quote_plus(address)}",
        "price": None,
        "rentability_notes": None,
        "status": "Not checked",
    }

    html = fetch_url(result["search_url"], timeout=20)
    if not html:
        result["status"] = "Unable to fetch Trulia page"
        return result

    price = regex_money_from_text(
        html,
        [
            r'"price"\s*:\s*"?\$?([\d,]+)"?',
            r'"formattedPrice"\s*:\s*"?\$?([\d,]+)"?',
        ],
    )

    notes = []
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True).lower()

    # simple neighborhood/renter-retention signal keywords
    keyword_hits = {
        "near schools": "near schools" in page_text,
        "quiet": "quiet" in page_text,
        "walkable": "walkable" in page_text,
        "transit": "transit" in page_text,
        "shopping": "shopping" in page_text,
        "family friendly": "family friendly" in page_text,
    }
    for k, v in keyword_hits.items():
        if v:
            notes.append(k)

    result["price"] = price
    result["rentability_notes"] = ", ".join(notes) if notes else None
    result["status"] = "Fetched" if (price or notes) else "Fetched page, limited parsing"
    return result


def extract_greatschools_data(address):
    """
    GreatSchools scraping is often blocked or HTML is dynamic.
    This tries a basic search page lookup.
    """
    result = {
        "source": "GreatSchools",
        "search_url": f"https://www.greatschools.org/search/search.page?q={quote_plus(address)}",
        "elementary_rating": None,
        "status": "Not checked",
    }

    html = fetch_url(result["search_url"], timeout=20)
    if not html:
        result["status"] = "Unable to fetch GreatSchools page"
        return result

    # Best-effort regex search for ratings like 7/10 or 8 out of 10
    patterns = [
        r'Elementary[^0-9]{0,120}(\d{1,2})\s*/\s*10',
        r'elementary[^0-9]{0,120}(\d{1,2})\s*out of\s*10',
        r'"rating"\s*:\s*"(\d{1,2})/10"',
    ]

    for p in patterns:
        m = re.search(p, html, re.IGNORECASE | re.DOTALL)
        if m:
            result["elementary_rating"] = safe_float(m.group(1), None)
            break

    result["status"] = "Fetched" if result["elementary_rating"] is not None else "Fetched page, rating not parsed"
    return result


def build_source_links(address, geo):
    city = geo.get("city", "")
    state = geo.get("state", "")
    zipcode = geo.get("postcode", "")
    county = geo.get("county", "")

    location_text = " ".join([x for x in [city, state, zipcode] if x]).strip()
    county_state = " ".join([x for x in [county, state] if x]).strip()

    return {
        "Zillow": f"https://www.zillow.com/homes/{quote_plus(address)}_rb/",
        "Trulia": f"https://www.trulia.com/home/{quote_plus(address)}",
        "GreatSchools": f"https://www.greatschools.org/search/search.page?q={quote_plus(address)}",
        "CommunityCrimeMap": f"https://communitycrimemap.com/?address={quote_plus(address)}",
        "Redfin Search": f"https://www.redfin.com/search?q={quote_plus(address)}",
        "City-Data": f"https://www.city-data.com/search/search.php?qs={quote_plus(location_text or address)}",
        "Census Reporter": f"https://censusreporter.org/search/?q={quote_plus(location_text or county_state or address)}",
        "Data Census": "https://data.census.gov/",
        "Redfin Data Center": "https://www.redfin.com/news/data-center/",
    }


def infer_rentability_score(trulia_notes, city_data_manual_note):
    """
    Best-effort qualitative score.
    """
    score = 50
    text = f"{trulia_notes or ''} {city_data_manual_note or ''}".lower()

    positive_terms = [
        "quiet", "walkable", "shopping", "transit",
        "family friendly", "stable", "good schools",
        "owner occupied", "long-term", "low turnover"
    ]
    negative_terms = [
        "high crime", "vacancy", "turnover", "noisy",
        "unstable", "declining", "blight", "unsafe"
    ]

    for term in positive_terms:
        if term in text:
            score += 8
    for term in negative_terms:
        if term in text:
            score -= 10

    return max(0, min(100, score))


def verdict_label(cash_flow):
    if cash_flow >= 300:
        return "Good Deal"
    if cash_flow >= 0:
        return "Borderline Deal"
    return "Bad Deal"


def crime_label(crime_manual_score):
    if crime_manual_score is None:
        return "Unknown"
    if crime_manual_score >= 70:
        return "High"
    if crime_manual_score >= 40:
        return "Moderate"
    return "Low"


# ============================================================
# CACHED LOOKUPS
# ============================================================
@st.cache_data(show_spinner=False, ttl=3600)
def analyze_sources(address):
    geo = geocode_address_nominatim(address)
    census = get_census_tract_and_income(address)
    zillow = extract_zillow_data(address)
    trulia = extract_trulia_data(address)
    schools = extract_greatschools_data(address)
    links = build_source_links(address, geo)

    return {
        "geo": geo,
        "census": census,
        "zillow": zillow,
        "trulia": trulia,
        "schools": schools,
        "links": links,
    }


# ============================================================
# UI
# ============================================================
st.title("🏠 Rental Investment Analyzer")
st.caption("Enter a property address. The app will try to research the property and estimate whether it is a good rental deal.")

left, right = st.columns([1.1, 0.9])

with left:
    address = st.text_input(
        "Address",
        placeholder="3751 Oakwood Manor, Decatur, GA 30032",
    )

with right:
    st.write("")
    st.write("")
    run_analysis = st.button("Analyze Property", type="primary", use_container_width=True)

st.markdown("---")

# ============================================================
# DEFAULT INPUTS
# ============================================================
with st.expander("Financing & Manual Override Inputs", expanded=True):
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        interest_rate = st.number_input("Interest Rate (%)", min_value=0.0, max_value=20.0, value=7.0, step=0.1)
        loan_years = st.number_input("Loan Term (Years)", min_value=1, max_value=40, value=30, step=1)

    with c2:
        annual_insurance_manual = st.number_input("Annual Insurance ($)", min_value=0.0, value=1800.0, step=100.0)
        hoa_manual = st.number_input("Monthly HOA ($)", min_value=0.0, value=0.0, step=25.0)

    with c3:
        property_price_manual = st.number_input("Manual Purchase Price Override ($)", min_value=0.0, value=0.0, step=1000.0)
        annual_tax_manual = st.number_input("Manual Annual Property Tax Override ($)", min_value=0.0, value=0.0, step=100.0)

    with c4:
        rent_manual = st.number_input("Manual Estimated Rent Override ($/mo)", min_value=0.0, value=0.0, step=50.0)
        crime_manual_score = st.slider(
            "Crime Risk Score (manual, 0=low / 100=high)",
            min_value=0, max_value=100, value=50
        )

    st.caption("Use overrides when a site blocks automated extraction or when you want to use your own numbers.")

# ============================================================
# ANALYSIS
# ============================================================
if run_analysis and address.strip():
    with st.spinner("Researching property and calculating deal metrics..."):
        data = analyze_sources(address.strip())

    geo = data["geo"]
    census = data["census"]
    zillow = data["zillow"]
    trulia = data["trulia"]
    schools = data["schools"]
    links = data["links"]

    # ---------------------------
    # Final inputs for calculation
    # ---------------------------
    auto_price = zillow.get("price") or trulia.get("price")
    auto_rent = zillow.get("rent_estimate")
    auto_tax = zillow.get("property_tax_annual")
    auto_hoa = zillow.get("hoa_monthly")

    purchase_price = property_price_manual if property_price_manual > 0 else (auto_price or 0.0)
    estimated_rent = rent_manual if rent_manual > 0 else (auto_rent or 0.0)
    annual_tax = annual_tax_manual if annual_tax_manual > 0 else (auto_tax or 0.0)
    hoa_monthly = hoa_manual if hoa_manual > 0 else (auto_hoa or 0.0)
    annual_insurance = annual_insurance_manual

    down_payment = purchase_price * 0.30
    loan_amount = purchase_price - down_payment
    mortgage_pi = monthly_mortgage_payment(loan_amount, interest_rate, loan_years)

    monthly_tax = annual_tax / 12 if annual_tax else 0.0
    monthly_insurance = annual_insurance / 12 if annual_insurance else 0.0
    maintenance = estimated_rent * 0.10 if estimated_rent else 0.0
    vacancy = estimated_rent * 0.10 if estimated_rent else 0.0

    total_monthly_payment = (
        mortgage_pi
        + monthly_tax
        + monthly_insurance
        + hoa_monthly
        + maintenance
        + vacancy
    )

    monthly_cash_flow = estimated_rent - total_monthly_payment
    gross_rent_yield = ((estimated_rent * 12) / purchase_price * 100) if purchase_price > 0 and estimated_rent > 0 else 0.0
    cap_rate_proxy = (((estimated_rent * 12) - ((maintenance + vacancy + hoa_monthly) * 12) - annual_tax - annual_insurance) / purchase_price * 100) if purchase_price > 0 else 0.0
    rentability_score = infer_rentability_score(trulia.get("rentability_notes"), "")
    income = census.get("median_household_income")

    deal_verdict = verdict_label(monthly_cash_flow)

    # ---------------------------
    # Top summary
    # ---------------------------
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Estimated Purchase Price", fmt_money(purchase_price))
    s2.metric("Estimated Monthly Rent", fmt_money(estimated_rent))
    s3.metric("Total Monthly Cost", fmt_money(total_monthly_payment))
    s4.metric("Monthly Cash Flow", fmt_money(monthly_cash_flow))

    st.markdown("---")

    # ---------------------------
    # Property research section
    # ---------------------------
    a1, a2 = st.columns([1.05, 0.95])

    with a1:
        st.subheader("Property Research")

        st.write("**Address entered:**", address)
        if geo.get("display_name"):
            st.write("**Geocoded location:**", geo.get("display_name"))

        property_df = pd.DataFrame([
            {
                "Category": "Zillow price",
                "Value": fmt_money(zillow.get("price")) if zillow.get("price") else "Not found",
                "Status": zillow.get("status"),
            },
            {
                "Category": "Zillow rent estimate",
                "Value": fmt_money(zillow.get("rent_estimate")) if zillow.get("rent_estimate") else "Not found",
                "Status": zillow.get("status"),
            },
            {
                "Category": "GreatSchools elementary rating",
                "Value": f"{schools.get('elementary_rating')}/10" if schools.get("elementary_rating") is not None else "Not found",
                "Status": schools.get("status"),
            },
            {
                "Category": "Median household income",
                "Value": fmt_money(income) if income else "Not found",
                "Status": "From Census ACS via tract lookup" if income else "Not found",
            },
            {
                "Category": "Rentability score",
                "Value": f"{rentability_score}/100",
                "Status": "Best-effort signal from available neighborhood text",
            },
            {
                "Category": "Crime level",
                "Value": crime_label(crime_manual_score),
                "Status": "Manual score + review CommunityCrimeMap/Redfin links",
            },
        ])
        st.dataframe(property_df, use_container_width=True, hide_index=True)

        st.subheader("Deal Verdict")
        if deal_verdict == "Good Deal":
            st.success(
                f"**{deal_verdict}** — Estimated rent exceeds total monthly cost by {fmt_money(monthly_cash_flow)}."
            )
        elif deal_verdict == "Borderline Deal":
            st.warning(
                f"**{deal_verdict}** — Property is close to breakeven with estimated monthly cash flow of {fmt_money(monthly_cash_flow)}."
            )
        else:
            st.error(
                f"**{deal_verdict}** — Estimated monthly cash flow is negative by {fmt_money(abs(monthly_cash_flow))}."
            )

        verdict_notes = []
        if schools.get("elementary_rating") is not None:
            if schools["elementary_rating"] >= 7:
                verdict_notes.append("School rating appears supportive for family renters.")
            elif schools["elementary_rating"] < 5:
                verdict_notes.append("School rating may weaken long-term renter demand.")

        if income:
            rent_to_income = (estimated_rent * 12 / income * 100) if income > 0 and estimated_rent > 0 else None
            if rent_to_income is not None:
                verdict_notes.append(f"Estimated annual rent is about {rent_to_income:.1f}% of median household income.")

        if rentability_score >= 65:
            verdict_notes.append("Neighborhood signals suggest stronger long-term renter retainability.")
        elif rentability_score < 45:
            verdict_notes.append("Neighborhood signals suggest weaker renter retainability.")

        if gross_rent_yield > 0:
            verdict_notes.append(f"Gross rent yield is approximately {gross_rent_yield:.2f}%.")
        if cap_rate_proxy > 0:
            verdict_notes.append(f"Cap rate proxy is approximately {cap_rate_proxy:.2f}%.")

        for note in verdict_notes:
            st.write("-", note)

    with a2:
        st.subheader("Monthly Payment Breakdown")

        breakdown_df = pd.DataFrame([
            {"Item": "Mortgage + Interest", "Monthly": mortgage_pi},
            {"Item": "Property Tax", "Monthly": monthly_tax},
            {"Item": "Insurance", "Monthly": monthly_insurance},
            {"Item": "HOA", "Monthly": hoa_monthly},
            {"Item": "Maintenance (10% of rent)", "Monthly": maintenance},
            {"Item": "Vacancy (10% of rent)", "Monthly": vacancy},
            {"Item": "Total Monthly Cost", "Monthly": total_monthly_payment},
        ])
        breakdown_df["Monthly"] = breakdown_df["Monthly"].map(fmt_money)
        st.dataframe(breakdown_df, use_container_width=True, hide_index=True)

        st.subheader("Key Deal Ratios")
        r1, r2, r3 = st.columns(3)
        r1.metric("Down Payment (30%)", fmt_money(down_payment))
        r2.metric("Gross Rent Yield", f"{gross_rent_yield:.2f}%")
        r3.metric("Cap Rate Proxy", f"{cap_rate_proxy:.2f}%")

        st.subheader("Source Links")
        st.markdown(f"- [Zillow]({links['Zillow']})")
        st.markdown(f"- [Trulia]({links['Trulia']})")
        st.markdown(f"- [GreatSchools]({links['GreatSchools']})")
        st.markdown(f"- [CommunityCrimeMap]({links['CommunityCrimeMap']})")
        st.markdown(f"- [Redfin Search]({links['Redfin Search']})")
        st.markdown(f"- [City-Data]({links['City-Data']})")
        st.markdown(f"- [Census Reporter]({links['Census Reporter']})")
        st.markdown(f"- [Data Census]({links['Data Census']})")
        st.markdown(f"- [Redfin Data Center]({links['Redfin Data Center']})")

    st.markdown("---")

    # ---------------------------
    # Raw source extraction
    # ---------------------------
    st.subheader("Raw Extraction Results")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**Zillow**")
        st.json({
            "status": zillow.get("status"),
            "price": zillow.get("price"),
            "rent_estimate": zillow.get("rent_estimate"),
            "property_tax_annual": zillow.get("property_tax_annual"),
            "hoa_monthly": zillow.get("hoa_monthly"),
            "search_url": zillow.get("search_url"),
        })

    with c2:
        st.markdown("**Trulia**")
        st.json({
            "status": trulia.get("status"),
            "price": trulia.get("price"),
            "rentability_notes": trulia.get("rentability_notes"),
            "search_url": trulia.get("search_url"),
        })

    with c3:
        st.markdown("**GreatSchools / Census**")
        st.json({
            "greatschools_status": schools.get("status"),
            "elementary_rating": schools.get("elementary_rating"),
            "census_tract": census.get("tract_name"),
            "median_household_income": census.get("median_household_income"),
        })

    st.info(
        "Some sites may block automation. When that happens, use the source links above and enter manual overrides for price, taxes, HOA, or rent."
    )

elif run_analysis and not address.strip():
    st.warning("Please enter an address first.")

else:
    st.markdown(
        """
        ### What this app does
        - Looks up the address and tries to gather property/income/school data
        - Uses 30% down payment
        - Includes mortgage, tax, insurance, HOA, maintenance, and vacancy
        - Compares estimated monthly rent with estimated monthly cost
        - Gives a rental deal verdict

        ### Notes
        - Maintenance = 10% of estimated rent
        - Vacancy = 10% of estimated rent
        - Insurance is entered manually by default
        - Crime is best handled by reviewing CommunityCrimeMap and Redfin manually, then adjusting the crime score
        """
    )