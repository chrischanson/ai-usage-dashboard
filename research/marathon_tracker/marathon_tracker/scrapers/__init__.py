from typing import Callable
from ..models import Race, RaceResult
import importlib

def get_scraper(race_id: str) -> Callable[[Race], RaceResult] | None:
    """
    Dynamically loads a custom scraper for the given race_id if it exists.
    Returns the `extract` function from the scraper module, or None.
    """
    module_name = race_id.replace('-', '_')
    try:
        module = importlib.import_module(f".{module_name}", package=__name__)
        if hasattr(module, 'extract'):
            return getattr(module, 'extract')
    except ImportError:
        pass
    
    return None
