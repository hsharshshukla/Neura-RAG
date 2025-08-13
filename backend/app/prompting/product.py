# app/prompting/product.py
from functools import lru_cache
from typing import List

OPENTEXT_PRODUCTS: List[str] = [
    "OpenText Extended ECM (xECM)", "OpenText Content Server", "OpenText Core Content",
    "OpenText Documentum", "OpenText Intelligent Capture", "OpenText Captiva",
    "OpenText Solution Extensions", "OpenText Cloud Editions (CE)", "Aviator AI",
    "MyAviator", "Content Aviator", "Cybersecurity Aviator", "DevOps Aviator",
    "Experience Aviator", "Service Management Aviator", "OpenText Analytics Cloud",
    "OpenText Business Network Cloud", "OpenText Cybersecurity Cloud",
    "OpenText Observability & Service Management Cloud", "OpenText DevOps Cloud",
    "OpenText Experience Cloud", "OpenText Device and Data Protection",
    "UFT One", "SiteScope", "ZENworks", "GroupWise", "EnCase Forensic",
    "Fortify", "ArcSight", "Webroot", "Carbonite", "NetIQ", "Voltage",
    "Magellan", "RightFax", "Vertica", "Hightail", "SMAX", "Service Management Automation X"
]

_SCOPE_KEYWORDS = {
    "xecm","extended ecm","content server","otcs","core content","documentum","captiva","intelligent capture",
    "archive link","archivelink","content aviator","aviator","smax","sitescope","uft","fortify","arcsight",
    "rightfax","voltage","netiq","carbonite","webroot","magellan","vertica","hightail","groupwise","zenworks",
    "workspace","category","attribute","document type","rendition","dmcl","dql","dfs","taskspace","d2",
    "ce 23","ce 24","cloud editions","brava","archive center","record declaration","document declaration",
    "sap archive link","sap archivelink","s4hana","ecc","kpro","oac2","oac3","oac0","oact",
    "content server web services","csweb","smart view"
}

def infer_scope_products(text: str) -> list[str]:
    t = (text or "").lower()
    found: list[str] = []
    for p in OPENTEXT_PRODUCTS:
        base = p.lower().split(" (")[0]
        if base in t or any(tok and tok in t for tok in base.split()):
            if p not in found:
                found.append(p)
    if not found and any(k in t for k in _SCOPE_KEYWORDS):
        found.append("OpenText (unspecified)")
    return found

@lru_cache(maxsize=4)
def make_system_prompt(grounded: bool) -> str:
    base = """
You are **Neura**, an OpenText-only expert consultant and solutions architect.

# Scope
- You ONLY answer about the following OpenText products and adjacent topics:
  - {products}.
- If the user asks about anything outside those, **politely decline** and state your scope is OpenText products only. Suggest uploading relevant OpenText docs or specifying the product/version.

# Guardrails
- Use ONLY the provided context when available. **Do not** invent APIs, config keys, or UI labels.
- **Never** reveal or guess document/file names, owners, paths, repository IDs, URLs, or links—even if asked.
- If the answer is not in context, say "I don't have enough information from the provided materials." Then list what to collect next (logs, exact UI path, config export).

# Answer style
- Start with a brief **Summary** (1–3 lines).
- Then give **Step-by-step** instructions with exact **UI paths** or **commands/config snippets**.
- Include **Prerequisites**, **Validation/Smoke tests**, and **Rollback** where relevant.
- Call out **Version notes** (CE vs on-prem, CE 23.x vs 24.x, Documentum D2/TaskSpace, SAP ECC vs S/4HANA ArchiveLink).
- End with **Common pitfalls & tips**.

# Tone
- Concise, practical, production-oriented. Prefer checklists and bullets over prose.
""".strip().format(products=", ".join(OPENTEXT_PRODUCTS))

    extra = (
        "\n\n# Context mode\nGround the answer strictly in the provided excerpts. If not present, say so."
        if grounded else
        "\n\n# No-context mode\nAnswer using OpenText expertise but stay within scope. If risky, include cautions."
    )
    return base + extra
