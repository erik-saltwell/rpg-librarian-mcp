"""Atomic RPGGeek operations."""

from ._client import Candidate, ProductDetails, get_rpggeek_product, search_rpggeek

search = search_rpggeek
get_product = get_rpggeek_product

__all__ = ["Candidate", "ProductDetails", "get_product", "search"]
