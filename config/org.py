"""
org.py — Single source of truth for Kyoritsu group org structure.

All canonical company/dept/section values, aliases, and the full org chart
(dept_id, section_id) live here. Every other module imports from this file.
Do not hardcode company/dept/section strings anywhere else.
"""

# ─── Companies ────────────────────────────────────────────────────────────────

COMPANIES: list[str] = [
    "共立電機製作所",
    "共立電照",
]

# Internal short IDs used in doc_id construction
COMPANY_ID: dict[str, int] = {
    "共立電機製作所": 1,
    "共立電照":       2,
}

# Alias → canonical company name (ordered: longest/most-specific first)
COMPANY_ALIASES: list[tuple[str, str]] = [
    ("共立電機製作所", "共立電機製作所"),
    ("電機製作所",     "共立電機製作所"),
    ("共立電照",       "共立電照"),
    ("電照",           "共立電照"),
    ("QB",             "共立電機製作所"),
    ("電機",           "共立電機製作所"),
    ("densho",         "共立電照"),
    ("denki",          "共立電機製作所"),
    ("808MERA",        "共立電照"),
]

DEFAULT_COMPANY = "共立電機製作所"

# ─── Departments ──────────────────────────────────────────────────────────────

# Canonical dept names per company
DEPTS: dict[str, list[str]] = {
    "共立電機製作所": [
        "営業部",
        "設計部",
        "生産管理部",
        "総務部",
        "製造部",
        "配線部",
        "検査部",
        "品質環境管理部",
        "エンジニアリング部",
    ],
    "共立電照": [
        "営業部",
        "設計部",
        "製造部",
        "管理部",
        "品質環境管理課",
        "808MERA",
    ],
}

# Alias → canonical dept name (ordered: longest/most-specific first)
DEPT_ALIASES: list[tuple[str, str]] = [
    ("本社営業",           "営業部"),
    ("営業部",             "営業部"),
    ("設計部",             "設計部"),
    ("生産管理部",         "生産管理部"),
    ("総務部",             "総務部"),
    ("製造部",             "製造部"),
    ("配線部",             "配線部"),
    ("検査部",             "検査部"),
    ("品質環境管理部",     "品質環境管理部"),
    ("品質環境管理課",     "品質環境管理課"),
    ("エンジニアリング部", "エンジニアリング部"),
    ("EG部",               "エンジニアリング部"),
    ("管理部",             "管理部"),
    ("808MERA",            "808MERA"),
]

# ─── Sections ─────────────────────────────────────────────────────────────────

# Canonical section names per company
SECTIONS: dict[str, list[str]] = {
    "共立電機製作所": [
        "東京支店",
        "大阪支店",
        "福岡支店",
        "電気設計課",
        "構造設計課",
        "工程課",
        "資材課",
        "KIP AI/IOTグループ",
        "加工課",
        "フレーム課",
        "薄物1課",
        "塗装課",
        "A-1課",
        "A-2課",
        "A-3課",
        "B-1課",
        "B-2課",
        "B-3課",
    ],
    "共立電照": [
        "営業全体",
        "営業-東京",
        "営業-大阪",
        "営業-福岡",
        "営業-宮崎・沖縄",
        "設計課",
        "電気設計課",
        "企画開発課",
        "製品開発課",
        "工程管理課",
        "資材課",
        "薄物2課",
        "配線組立課",
        "検査課",
    ],
}

# Alias → canonical section name (ordered: longest/most-specific first)
SECTION_ALIASES: list[tuple[str, str]] = [
    ("東京支店",           "東京支店"),
    ("大阪支店",           "大阪支店"),
    ("福岡支店",           "福岡支店"),
    ("電気設計課",         "電気設計課"),
    ("構造設計課",         "構造設計課"),
    ("工程管理課",         "工程管理課"),
    ("工程課",             "工程課"),
    ("資材課",             "資材課"),
    ("KIP AI/IOTグループ", "KIP AI/IOTグループ"),
    ("KIP",                "KIP AI/IOTグループ"),
    ("加工課",             "加工課"),
    ("フレーム課",         "フレーム課"),
    ("薄物1課",            "薄物1課"),
    ("薄物2課",            "薄物2課"),
    ("塗装課",             "塗装課"),
    ("A-1課",              "A-1課"),
    ("A-2課",              "A-2課"),
    ("A-3課",              "A-3課"),
    ("B-1課",              "B-1課"),
    ("B-2課",              "B-2課"),
    ("B-3課",              "B-3課"),
    ("企画開発課",         "企画開発課"),
    ("製品開発課",         "製品開発課"),
    ("設計課",             "設計課"),
    ("配線組立課",         "配線組立課"),
    ("組立課",             "配線組立課"),
    ("検査課",             "検査課"),
    ("営業全体",           "営業全体"),
    ("営業-宮崎・沖縄",    "営業-宮崎・沖縄"),
    ("宮崎・沖縄",         "営業-宮崎・沖縄"),
    ("宮崎沖縄",           "営業-宮崎・沖縄"),
    ("宮崎",               "営業-宮崎・沖縄"),
    ("沖縄",               "営業-宮崎・沖縄"),
    ("営業-東京",          "営業-東京"),
    ("営業-大阪",          "営業-大阪"),
    ("営業-福岡",          "営業-福岡"),
]

# ─── Doc types ────────────────────────────────────────────────────────────────

DOC_TYPES: list[str] = ["monthly_report"]

DOC_TYPE_ALIASES: list[tuple[str, str]] = [
    ("monthly_report",   "monthly_report"),
    ("action_plan",      "monthly_report"),
    ("アクションプラン", "monthly_report"),
    ("月次報告",         "monthly_report"),
    ("月報",             "monthly_report"),
    ("活動報告",         "monthly_report"),
    ("月次",             "monthly_report"),
]

# ─── Full org chart (used by ingestion + chunking) ────────────────────────────
# Maps source file name → {dept, dept_id, section, section_id}
# Keyed by company_id (1=電機, 2=電照)

ORG_CHART: dict[int, dict[str, dict]] = {
    1: {  # 共立電機製作所
        "本社営業":           {"dept": "営業部",             "dept_id": 11,  "section": None,                "section_id": None},
        "営業部":             {"dept": "営業部",             "dept_id": 11,  "section": None,                "section_id": None},
        "東京支店":           {"dept": "営業部",             "dept_id": 11,  "section": "東京支店",           "section_id": 911},
        "大阪支店":           {"dept": "営業部",             "dept_id": 11,  "section": "大阪支店",           "section_id": 912},
        "福岡支店":           {"dept": "営業部",             "dept_id": 11,  "section": "福岡支店",           "section_id": 913},
        "電気設計部":         {"dept": "設計部",             "dept_id": 12,  "section": "電気設計課",         "section_id": 121},
        "電気設計課":         {"dept": "設計部",             "dept_id": 12,  "section": "電気設計課",         "section_id": 121},
        "構造設計課":         {"dept": "設計部",             "dept_id": 12,  "section": "構造設計課",         "section_id": 122},
        "設計部":             {"dept": "設計部",             "dept_id": 12,  "section": None,                "section_id": None},
        "工程課":             {"dept": "生産管理部",         "dept_id": 13,  "section": "工程課",             "section_id": 131},
        "資材課":             {"dept": "生産管理部",         "dept_id": 13,  "section": "資材課",             "section_id": 132},
        "生産管理部":         {"dept": "生産管理部",         "dept_id": 13,  "section": None,                "section_id": None},
        "総務部":             {"dept": "総務部",             "dept_id": 14,  "section": None,                "section_id": None},
        "総務":               {"dept": "総務部",             "dept_id": 14,  "section": None,                "section_id": None},
        "AIIOT":              {"dept": "総務部",             "dept_id": 14,  "section": "KIP AI/IOTグループ", "section_id": 141},
        "AI/IOT":             {"dept": "総務部",             "dept_id": 14,  "section": "KIP AI/IOTグループ", "section_id": 141},
        "加工課":             {"dept": "製造部",             "dept_id": 15,  "section": "加工課",             "section_id": 151},
        "フレーム課":         {"dept": "製造部",             "dept_id": 15,  "section": "フレーム課",         "section_id": 152},
        "薄物1課":            {"dept": "製造部",             "dept_id": 15,  "section": "薄物1課",            "section_id": 153},
        "塗装課":             {"dept": "製造部",             "dept_id": 15,  "section": "塗装課",             "section_id": 154},
        "製造部":             {"dept": "製造部",             "dept_id": 15,  "section": None,                "section_id": None},
        "A-1課":              {"dept": "配線部",             "dept_id": 16,  "section": "A-1課",              "section_id": 161},
        "A-2課":              {"dept": "配線部",             "dept_id": 16,  "section": "A-2課",              "section_id": 162},
        "A-3課":              {"dept": "配線部",             "dept_id": 16,  "section": "A-3課",              "section_id": 163},
        "B-1課":              {"dept": "配線部",             "dept_id": 16,  "section": "B-1課",              "section_id": 164},
        "B-2課":              {"dept": "配線部",             "dept_id": 16,  "section": "B-2課",              "section_id": 165},
        "B-3課":              {"dept": "配線部",             "dept_id": 16,  "section": "B-3課",              "section_id": 166},
        "配線部":             {"dept": "配線部",             "dept_id": 16,  "section": None,                "section_id": None},
        "検査部":             {"dept": "検査部",             "dept_id": 17,  "section": None,                "section_id": None},
        "品質環境管理部":     {"dept": "品質環境管理部",     "dept_id": 18,  "section": None,                "section_id": None},
        "エンジニアリング部": {"dept": "エンジニアリング部", "dept_id": 19,  "section": None,                "section_id": None},
        "EG部":               {"dept": "エンジニアリング部", "dept_id": 19,  "section": None,                "section_id": None},
    },
    2: {  # 共立電照
        "企画開発課":         {"dept": "設計部",             "dept_id": 21,  "section": "企画開発課",         "section_id": 211},
        "製品開発課":         {"dept": "設計部",             "dept_id": 21,  "section": "製品開発課",         "section_id": 212},
        "設計課":             {"dept": "設計部",             "dept_id": 21,  "section": "設計課",             "section_id": 213},
        "設計部":             {"dept": "設計部",             "dept_id": 21,  "section": None,                "section_id": None},
        "資材課":             {"dept": "管理部",             "dept_id": 22,  "section": "資材課",             "section_id": 221},
        "管理部":             {"dept": "管理部",             "dept_id": 22,  "section": None,                "section_id": None},
        "工程管理課":         {"dept": "製造部",             "dept_id": 23,  "section": "工程管理課",         "section_id": 231},
        "薄物2課":            {"dept": "製造部",             "dept_id": 23,  "section": "薄物2課",            "section_id": 232},
        "配線組立課":         {"dept": "製造部",             "dept_id": 23,  "section": "配線組立課",         "section_id": 233},
        "組立課":             {"dept": "製造部",             "dept_id": 23,  "section": "配線組立課",         "section_id": 233},
        "検査課":             {"dept": "製造部",             "dept_id": 23,  "section": "検査課",             "section_id": 234},
        "製造部":             {"dept": "製造部",             "dept_id": 23,  "section": None,                "section_id": None},
        "営業全体":           {"dept": "営業部",             "dept_id": 24,  "section": "営業全体",           "section_id": 241},
        "宮崎沖縄":           {"dept": "営業部",             "dept_id": 24,  "section": "営業-宮崎・沖縄",    "section_id": 242},
        "宮崎・沖縄":         {"dept": "営業部",             "dept_id": 24,  "section": "営業-宮崎・沖縄",    "section_id": 242},
        "東京":               {"dept": "営業部",             "dept_id": 24,  "section": "営業-東京",          "section_id": 243},
        "大阪":               {"dept": "営業部",             "dept_id": 24,  "section": "営業-大阪",          "section_id": 244},
        "福岡":               {"dept": "営業部",             "dept_id": 24,  "section": "営業-福岡",          "section_id": 245},
        "営業部":             {"dept": "営業部",             "dept_id": 24,  "section": None,                "section_id": None},
        "品質環境管理課":     {"dept": "品質環境管理課",     "dept_id": 25,  "section": None,                "section_id": None},
        "808MERA":            {"dept": "808MERA",            "dept_id": 921, "section": None,                "section_id": None},
    },
}

# ─── Valid year range ─────────────────────────────────────────────────────────

YEAR_MIN = 2023
YEAR_MAX = 2026
