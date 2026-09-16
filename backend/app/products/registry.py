"""Registry of products the dashboard knows how to parse and serve.

To onboard a new product (e.g. Nimco, Pops):
  1. Drop its workbook into backend/data/raw/<slug>/
  2. Add a ProductConfig entry to PRODUCTS below
  3. Run `python backend/scripts/build_cache.py --product <slug>`
  4. (Later, once multi-product UI exists) register it in the frontend's product
     switcher -- see the NOTE in frontend/js/app.js for where that would hook in.
No changes to the parser, API, or cache layers should be required.
"""
from dataclasses import dataclass, field

from ..config import RAW_DATA_DIR


@dataclass
class ProductConfig:
    slug: str
    display_name: str
    excel_path: str  # path relative to RAW_DATA_DIR, or absolute
    sheet_skip_keywords: list[str] = field(default_factory=lambda: ["Summary", "Link"])
    skip_if_paren_in_name: bool = True

    @property
    def resolved_excel_path(self):
        from pathlib import Path

        p = Path(self.excel_path)
        if p.is_absolute():
            return p
        return RAW_DATA_DIR / p


PRODUCTS: dict[str, ProductConfig] = {
    "fryo": ProductConfig(
        slug="fryo",
        display_name="Fry-O",
        excel_path="fryo/FryO Packing OEE 09-09-26.xlsx",
    ),
    # Future: "nimco": ProductConfig(slug="nimco", display_name="Nimco",
    #                                 excel_path="nimco/<workbook>.xlsx"),
    # Future: "pops":  ProductConfig(slug="pops",  display_name="Pops",
    #                                 excel_path="pops/<workbook>.xlsx"),
}


def get_product(slug: str) -> ProductConfig | None:
    return PRODUCTS.get(slug)
