import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# DB path is configurable so dev (Mac) and prod (Arch /data) differ without code changes.
DB_PATH = os.getenv("DB_PATH", "/data/civic.db")
PORT = int(os.getenv("PORT", "8902"))
# Absolute base URL for canonical tags + sitemap. Set to the real domain at deploy.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8902").rstrip("/")

# Legistar Web API — Clark County's public records API. Client slug "clark"; no key required.
LEGISTAR_CLIENT = os.getenv("LEGISTAR_CLIENT", "clark")
LEGISTAR_BASE = f"https://webapi.legistar.com/v1/{LEGISTAR_CLIENT}"
# Official public-facing meeting portal (for "verify against the official record" links).
LEGISTAR_INSITE = os.getenv("LEGISTAR_INSITE", "https://clark.legistar.com")

# Gemma via MLX (OpenAI-compatible chat API). On Arch, point MLX_URL at the Mac's LAN IP
# (http://192.168.0.79:8321) — MLX lives on the Mac. Summaries are best-effort: if MLX is
# unreachable the pages still render (raw agenda), so a Tailscale/LAN hiccup never breaks the site.
MLX_URL = os.getenv("MLX_URL", "http://127.0.0.1:8321").rstrip("/")
MLX_MODEL = os.getenv("MLX_MODEL", "mlx-community/gemma-4-26b-a4b-it-4bit")

# Phase 1 = Clark County's three highest-impact bodies (budget, land use, development), keyed by
# Legistar BodyId. `slug` drives the public URL (/body/{slug}); `name` is the human label.
BODIES = {
    138: {"slug": "board-of-commissioners", "name": "Board of Commissioners"},
    180: {"slug": "planning-commission", "name": "Planning Commission"},
    181: {"slug": "zoning-commission", "name": "Zoning Commission"},
}

# Mandatory disclaimer rendered on every AI-summarized surface (accuracy/liability + honesty).
AI_DISCLAIMER = ("AI-generated summary — it can be wrong or incomplete. "
                 "Always verify against the official record before relying on it.")
