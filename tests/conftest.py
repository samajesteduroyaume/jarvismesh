import asyncio
import inspect
import sys
from pathlib import Path

# Ajoute la racine du projet au sys.path pour les tests
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def pytest_pyfunc_call(pyfuncitem):
    """Exécute automatiquement les fonctions de test asynchrones (async def)
    dans une boucle d'événements asyncio sans nécessiter de plugin externe."""
    testfunction = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunction):
        args = [pyfuncitem.funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames]
        asyncio.run(testfunction(*args))
        return True
