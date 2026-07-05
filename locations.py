"""
Static data: world countries, major cities, and popular job title suggestions.
"""

# ── Job titles grouped by domain ──────────────────────────────────────────────
JOB_TITLES: dict[str, list[str]] = {
    "Software Engineering": [
        "Software Engineer", "Senior Software Engineer", "Staff Software Engineer",
        "Principal Software Engineer", "Full Stack Developer", "Frontend Developer",
        "Backend Developer", "Embedded Systems Engineer", "Platform Engineer",
        "Site Reliability Engineer (SRE)", "Engineering Manager", "VP of Engineering",
    ],
    "Data & AI": [
        "Data Scientist", "Senior Data Scientist", "Machine Learning Engineer",
        "AI Engineer", "NLP Engineer", "Computer Vision Engineer",
        "Data Engineer", "Analytics Engineer", "Data Analyst",
        "Business Intelligence Analyst", "Data Architect", "MLOps Engineer",
        "Research Scientist", "Quantitative Analyst",
    ],
    "Cloud & DevOps": [
        "DevOps Engineer", "Cloud Engineer", "Cloud Architect",
        "AWS Solutions Architect", "Azure Engineer", "GCP Engineer",
        "Kubernetes Engineer", "Infrastructure Engineer", "Security Engineer",
        "Penetration Tester", "Platform Engineer",
    ],
    "Mobile": [
        "iOS Developer", "Android Developer", "React Native Developer",
        "Flutter Developer", "Mobile Engineer",
    ],
    "Product & Design": [
        "Product Manager", "Senior Product Manager", "Technical Product Manager",
        "Product Owner", "UX Designer", "UI Designer", "Product Designer",
        "UX Researcher", "UX Writer", "Graphic Designer", "Motion Designer",
        "Design Lead",
    ],
    "Finance & Accounting": [
        "Financial Analyst", "Senior Financial Analyst", "FP&A Analyst",
        "Investment Analyst", "Portfolio Manager", "Risk Analyst",
        "Quantitative Analyst", "Accountant", "Controller", "CFO",
        "Audit Manager", "Tax Specialist", "Finance Manager",
    ],
    "Marketing": [
        "Digital Marketing Manager", "SEO Specialist", "Content Manager",
        "Growth Manager", "Social Media Manager", "Performance Marketing Manager",
        "Brand Manager", "Email Marketing Specialist", "CMO", "Marketing Analyst",
        "Product Marketing Manager",
    ],
    "Sales & Business Development": [
        "Account Executive", "Sales Manager", "Enterprise Sales Manager",
        "Business Development Manager", "Inside Sales Representative",
        "Sales Director", "VP of Sales", "Customer Success Manager",
        "Solutions Engineer", "Pre-Sales Engineer",
    ],
    "Human Resources": [
        "HR Manager", "HR Business Partner", "Talent Acquisition Specialist",
        "Technical Recruiter", "Recruiter", "HR Director", "CHRO",
        "Compensation & Benefits Manager", "L&D Manager",
    ],
    "Operations & Management": [
        "Operations Manager", "Project Manager", "Program Manager",
        "Scrum Master", "Agile Coach", "Business Analyst",
        "Supply Chain Manager", "Logistics Manager", "COO", "CEO",
    ],
    "Customer Service": [
        "Customer Service Manager", "Customer Support Specialist",
        "Technical Support Engineer", "Customer Experience Manager",
    ],
    "Legal & Compliance": [
        "Legal Counsel", "Compliance Officer", "Paralegal",
        "Data Privacy Officer", "Contract Manager",
    ],
}

# Flat sorted list used in the selectbox
ALL_JOB_TITLES: list[str] = sorted(
    {title for titles in JOB_TITLES.values() for title in titles}
)


# ── Countries → major cities ──────────────────────────────────────────────────
WORLD_LOCATIONS: dict[str, list[str]] = {
    # ── Remote first so it appears at the top ─────────────────────────────────
    "Remote (Worldwide)": [
        "Remote – Worldwide", "Remote – US Only", "Remote – Europe",
        "Remote – Asia Pacific", "Remote – LATAM",
    ],

    # ── Americas ──────────────────────────────────────────────────────────────
    "Argentina": ["Buenos Aires", "Córdoba", "Rosario", "Mendoza", "La Plata", "Tucumán"],
    "Brazil": [
        "São Paulo", "Rio de Janeiro", "Brasília", "Salvador",
        "Fortaleza", "Curitiba", "Belo Horizonte", "Manaus", "Recife",
    ],
    "Canada": [
        "Toronto", "Vancouver", "Montréal", "Calgary", "Ottawa",
        "Edmonton", "Québec City", "Winnipeg", "Halifax",
    ],
    "Chile": ["Santiago", "Valparaíso", "Concepción", "Antofagasta", "Viña del Mar"],
    "Colombia": ["Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena"],
    "Mexico": [
        "Mexico City", "Guadalajara", "Monterrey", "Puebla",
        "Querétaro", "Tijuana", "León", "Mérida",
    ],
    "Peru": ["Lima", "Arequipa", "Trujillo", "Cusco"],
    "United States": [
        "New York, NY", "San Francisco, CA", "Los Angeles, CA", "Seattle, WA",
        "Chicago, IL", "Boston, MA", "Austin, TX", "Denver, CO",
        "Atlanta, GA", "Washington, DC", "Dallas, TX", "Miami, FL",
        "San Diego, CA", "Portland, OR", "Phoenix, AZ", "Minneapolis, MN",
        "Nashville, TN", "Salt Lake City, UT", "Raleigh, NC", "Pittsburgh, PA",
    ],
    "Uruguay": ["Montevideo", "Punta del Este"],

    # ── Europe ────────────────────────────────────────────────────────────────
    "Austria": ["Vienna", "Graz", "Linz", "Salzburg", "Innsbruck"],
    "Belgium": ["Brussels", "Antwerp", "Ghent", "Liège", "Bruges"],
    "Czech Republic": ["Prague", "Brno", "Ostrava", "Plzeň"],
    "Denmark": ["Copenhagen", "Aarhus", "Odense", "Aalborg"],
    "Finland": ["Helsinki", "Tampere", "Turku", "Oulu"],
    "France": [
        "Paris", "Lyon", "Marseille", "Toulouse", "Bordeaux",
        "Nantes", "Strasbourg", "Lille", "Nice", "Montpellier",
    ],
    "Germany": [
        "Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne",
        "Stuttgart", "Düsseldorf", "Leipzig", "Dresden", "Nuremberg",
    ],
    "Greece": ["Athens", "Thessaloniki", "Patras", "Heraklion"],
    "Hungary": ["Budapest", "Debrecen", "Pécs", "Győr"],
    "Ireland": ["Dublin", "Cork", "Galway", "Limerick", "Waterford"],
    "Italy": ["Rome", "Milan", "Florence", "Turin", "Naples", "Bologna", "Venice"],
    "Netherlands": ["Amsterdam", "Rotterdam", "The Hague", "Utrecht", "Eindhoven"],
    "Norway": ["Oslo", "Bergen", "Trondheim", "Stavanger"],
    "Poland": ["Warsaw", "Kraków", "Wrocław", "Poznań", "Gdańsk", "Łódź", "Katowice"],
    "Portugal": ["Lisbon", "Porto", "Braga", "Coimbra", "Funchal"],
    "Romania": ["Bucharest", "Cluj-Napoca", "Timișoara", "Iași", "Brașov"],
    "Russia": ["Moscow", "Saint Petersburg", "Novosibirsk", "Yekaterinburg", "Kazan"],
    "Spain": [
        "Madrid", "Barcelona", "Valencia", "Seville", "Bilbao",
        "Málaga", "Zaragoza", "Alicante", "Granada",
    ],
    "Sweden": ["Stockholm", "Gothenburg", "Malmö", "Uppsala", "Linköping"],
    "Switzerland": ["Zurich", "Geneva", "Basel", "Bern", "Lausanne"],
    "Ukraine": ["Kyiv", "Lviv", "Kharkiv", "Odessa", "Dnipro"],
    "United Kingdom": [
        "London", "Manchester", "Birmingham", "Leeds", "Glasgow",
        "Edinburgh", "Bristol", "Liverpool", "Newcastle", "Cambridge",
        "Oxford", "Sheffield", "Nottingham",
    ],

    # ── Middle East & Africa ──────────────────────────────────────────────────
    "Egypt": ["Cairo", "Alexandria", "Giza", "Aswan", "Luxor"],
    "Israel": ["Tel Aviv", "Jerusalem", "Haifa", "Beer Sheva"],
    "Jordan": ["Amman", "Zarqa", "Irbid"],
    "Kenya": ["Nairobi", "Mombasa", "Kisumu"],
    "Morocco": ["Casablanca", "Rabat", "Marrakech", "Fes", "Tangier"],
    "Nigeria": ["Lagos", "Abuja", "Port Harcourt", "Kano", "Ibadan"],
    "Saudi Arabia": ["Riyadh", "Jeddah", "Dammam", "Mecca", "Medina"],
    "South Africa": [
        "Johannesburg", "Cape Town", "Durban", "Pretoria",
        "Port Elizabeth", "Stellenbosch",
    ],
    "UAE": ["Dubai", "Abu Dhabi", "Sharjah", "Ajman"],

    # ── Asia & Pacific ────────────────────────────────────────────────────────
    "Australia": [
        "Sydney", "Melbourne", "Brisbane", "Perth",
        "Adelaide", "Canberra", "Gold Coast",
    ],
    "Bangladesh": ["Dhaka", "Chittagong", "Sylhet", "Rajshahi"],
    "China": [
        "Beijing", "Shanghai", "Shenzhen", "Guangzhou", "Chengdu",
        "Hangzhou", "Wuhan", "Xi'an", "Chongqing", "Nanjing",
    ],
    "Hong Kong": ["Hong Kong"],
    "India": [
        "Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Chennai",
        "Pune", "Kolkata", "Ahmedabad", "Noida", "Gurugram",
        "Jaipur", "Chandigarh", "Coimbatore", "Kochi",
    ],
    "Indonesia": ["Jakarta", "Surabaya", "Bandung", "Medan", "Yogyakarta", "Bali"],
    "Japan": ["Tokyo", "Osaka", "Kyoto", "Yokohama", "Nagoya", "Fukuoka", "Sapporo"],
    "Malaysia": ["Kuala Lumpur", "Penang", "Johor Bahru", "Petaling Jaya", "Kota Kinabalu"],
    "New Zealand": ["Auckland", "Wellington", "Christchurch", "Hamilton"],
    "Pakistan": ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad"],
    "Philippines": ["Manila", "Cebu City", "Davao", "Quezon City", "Makati"],
    "Singapore": ["Singapore"],
    "South Korea": ["Seoul", "Busan", "Incheon", "Daegu", "Daejeon"],
    "Taiwan": ["Taipei", "Kaohsiung", "Taichung", "Tainan"],
    "Thailand": ["Bangkok", "Chiang Mai", "Phuket", "Pattaya"],
    "Vietnam": ["Ho Chi Minh City", "Hanoi", "Da Nang", "Hai Phong"],
}

# Country list for dropdown (first item = Remote)
COUNTRY_LIST: list[str] = list(WORLD_LOCATIONS.keys())


def get_cities(country: str) -> list[str]:
    """Return city list for a country, or an empty list."""
    return WORLD_LOCATIONS.get(country, [])


# Remote regions must map to locations LinkedIn's geo lookup understands —
# strings like "Remote US Only" return zero results.
_REMOTE_REGION_LOCATIONS: dict[str, str] = {
    "Worldwide":    "Worldwide",
    "US Only":      "United States",
    "Europe":       "European Union",
    "Asia Pacific": "Asia",
    "LATAM":        "Latin America",
}


def build_location_string(country: str, city: str) -> str:
    """
    Convert a (country, city) selection into the location string
    passed to the scraper.
    """
    if country == "Remote (Worldwide)":
        # city here is e.g. "Remote – Worldwide" or "Remote – Europe"
        if "–" in city:
            region = city.split("–", 1)[1].strip()
            return _REMOTE_REGION_LOCATIONS.get(region, "Worldwide")
        return "Worldwide"
    if not city or city == country:
        return country
    return f"{city}, {country}"


# ── Country-specific job platforms ────────────────────────────────────────────
COUNTRY_PLATFORMS: dict[str, list[str]] = {
    # Remote boards (RemoteOK/Remotive/Jobicy) ignore location — only
    # recommend them for remote searches.
    "Remote (Worldwide)": ["linkedin", "remoteok", "remotive", "jobicy"],
    # Americas
    "United States":  ["linkedin", "indeed", "themuse"],
    "Canada":         ["linkedin", "indeed", "themuse"],
    # South Asia
    "India":          ["linkedin", "indeed", "naukri"],
    "Pakistan":       ["linkedin", "rozee"],
    # Oceania
    "Australia":      ["linkedin", "seek"],
    "New Zealand":    ["linkedin", "seek"],
    # Middle East
    "UAE":            ["linkedin", "bayt"],
    "Saudi Arabia":   ["linkedin", "bayt"],
    "Jordan":         ["linkedin", "bayt"],
    "Egypt":          ["linkedin", "bayt"],
    # Europe
    "United Kingdom": ["linkedin", "indeed", "reed"],
    "Germany":        ["linkedin", "indeed", "arbeitnow"],
    "Austria":        ["linkedin", "indeed", "arbeitnow"],
    # SE Asia (JobStreet network)
    "Malaysia":       ["linkedin", "jobstreet"],
    "Philippines":    ["linkedin", "jobstreet"],
    "Singapore":      ["linkedin", "jobstreet"],
    "Indonesia":      ["linkedin", "jobstreet"],
}

PLATFORM_INFO: dict[str, dict] = {
    "linkedin":  {"name": "LinkedIn",            "url": "linkedin.com"},
    "indeed":    {"name": "Indeed*",             "url": "indeed.com"},
    "remoteok":  {"name": "RemoteOK (remote)",   "url": "remoteok.com"},
    "remotive":  {"name": "Remotive (remote)",   "url": "remotive.com"},
    "jobicy":    {"name": "Jobicy (remote)",     "url": "jobicy.com"},
    "arbeitnow": {"name": "Arbeitnow (DE/EU)",   "url": "arbeitnow.com"},
    "themuse":   {"name": "The Muse (US)",       "url": "themuse.com"},
    "naukri":    {"name": "Naukri",              "url": "naukri.com"},
    "seek":      {"name": "Seek",                "url": "seek.com.au"},
    "bayt":      {"name": "Bayt",                "url": "bayt.com"},
    "reed":      {"name": "Reed",                "url": "reed.co.uk"},
    "jobstreet": {"name": "JobStreet",           "url": "jobstreet.com"},
    "rozee":     {"name": "Rozee.pk",            "url": "rozee.pk"},
    "adzuna":    {"name": "Adzuna (API key)",    "url": "developer.adzuna.com"},
    "jooble":    {"name": "Jooble (API key)",    "url": "jooble.org/api/about"},
}
# * Indeed requires Playwright:  pip install playwright && playwright install chromium
# Adzuna needs ADZUNA_APP_ID + ADZUNA_APP_KEY env vars; Jooble needs JOOBLE_API_KEY.
# Reed automatically uses its official API when REED_API_KEY is set.

ALL_PLATFORMS: list[str] = list(PLATFORM_INFO.keys())


def get_recommended_sites(country: str) -> list[str]:
    """
    Return recommended job boards for a given country.
    Defaults to LinkedIn + Indeed (Indeed needs Playwright installed;
    it returns empty with a logged warning otherwise).
    """
    return COUNTRY_PLATFORMS.get(country, ["linkedin", "indeed"])
