"""
Tests unitaires pour le chargeur dynamique de compétences (SkillRegistry & @skill).
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.node import JarvisNode
from jarvismesh.skills import skill, SkillRegistry, default_registry


class MathPayload(BaseModel):
    a: int
    b: int


@skill(name="add_numbers", schema=MathPayload, description="Additionne deux nombres")
def add_numbers(payload: dict) -> dict:
    return {"sum": payload["a"] + payload["b"]}


async def test_skills_loader():
    print("== Test 1: Vérification du décorateur @skill ==")
    assert "add_numbers" in default_registry.skills
    assert "add_numbers" in default_registry.schemas
    assert default_registry.descriptions["add_numbers"] == "Additionne deux nombres"
    print("  -> @skill correctement enregistré dans le registre global")

    print("\n== Test 2: Chargement dynamique depuis un dossier ==")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Création d'un plugin custom
        plugin_code = """
from jarvismesh.skills import skill
from pydantic import BaseModel, Field

class MultiplyPayload(BaseModel):
    x: int
    y: int

@skill(name="multiply_numbers", schema=MultiplyPayload, description="Multiplie deux nombres")
def multiply_numbers(payload: dict) -> dict:
    return {"product": payload["x"] * payload["y"]}

@skill(name="uppercase_text")
def uppercase_text(payload: dict) -> dict:
    return {"text": payload.get("text", "").upper()}
"""
        (tmp_path / "custom_plugin.py").write_text(plugin_code, encoding="utf-8")

        custom_registry = SkillRegistry("test_custom")
        loaded_count = custom_registry.load_from_directory(tmp_path)
        print(f"  -> {loaded_count} compétences chargées depuis {tmp_path}")
        assert loaded_count == 2
        assert "multiply_numbers" in custom_registry.skills
        assert "uppercase_text" in custom_registry.skills

        print("\n== Test 3: Exécution via un JarvisNode ==")
        node = JarvisNode("test-loader-node", 9101, skills=custom_registry.skills, schemas=custom_registry.schemas)
        await node.start(enable_zeroconf=False)

        resp = await node.delegate("multiply_numbers", {"x": 6, "y": 7})
        print(f"  -> multiply: ok={resp.ok} result={resp.result}")
        assert resp.ok and resp.result["product"] == 42

        resp2 = await node.delegate("uppercase_text", {"text": "jarvismesh"})
        print(f"  -> uppercase: ok={resp2.ok} result={resp2.result}")
        assert resp2.ok and resp2.result["text"] == "JARVISMESH"

        await node.stop()

    print("\nTous les tests du chargeur de compétences sont passés avec succès !")


if __name__ == "__main__":
    asyncio.run(test_skills_loader())
