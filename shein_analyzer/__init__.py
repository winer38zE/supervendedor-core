"""
shein_analyzer — Análisis de tendencias Shein Colombia
"""

from shein_analyzer.scraper import SheinProduct, SheinScraper, save_products_to_excel, scrape_enterizos_deportivos

__all__ = ["SheinProduct", "SheinScraper", "save_products_to_excel", "scrape_enterizos_deportivos"]


def __getattr__(name: str):
    if name == "SheinProduct":
        from shein_analyzer.scraper import SheinProduct

        return SheinProduct
    if name == "SheinScraper":
        from shein_analyzer.scraper import SheinScraper

        return SheinScraper
    if name == "scrape_enterizos_deportivos":
        from shein_analyzer.scraper import scrape_enterizos_deportivos

        return scrape_enterizos_deportivos
    if name == "save_products_to_excel":
        from shein_analyzer.scraper import save_products_to_excel

        return save_products_to_excel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
