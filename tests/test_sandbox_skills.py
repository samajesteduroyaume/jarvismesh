"""
Tests pour la sandbox de code sécurisée et l'auto-programmation de compétences (jarvismesh.sandbox).
"""
import pytest
from jarvismesh.sandbox import (
    SandboxSkillExecutor,
    DynamicSkillManager,
    get_sandbox_skills,
)
from jarvismesh.skills import SkillRegistry


def test_sandbox_safety_validation():
    print("\n== Test Sandbox: Blocage des instructions dangereuses ==")
    
    # 1. Tentative d'importation système -> Rejeté
    dangerous_code_1 = "import os\nres = os.listdir('/')"
    safe1, err1 = SandboxSkillExecutor.validate_code_safety(dangerous_code_1)
    assert safe1 is False
    assert "interdites" in err1
    
    # 2. Tentative d'utilisation de eval / exec / open -> Rejeté
    dangerous_code_2 = "f = open('secret.txt', 'r')"
    safe2, err2 = SandboxSkillExecutor.validate_code_safety(dangerous_code_2)
    assert safe2 is False
    assert "open" in err2
    
    # 3. Code mathématique / logique pur -> Autorisé
    safe_code = "a = 10\nb = 20\nc = math.sqrt(a * b)"
    safe3, err3 = SandboxSkillExecutor.validate_code_safety(safe_code)
    assert safe3 is True
    assert err3 is None


def test_sandbox_execution():
    print("\n== Test Sandbox: Exécution isolée et récupération des variables ==")
    code = """
total = sum([x * 2 for x in items])
max_val = max(items)
"""
    res = SandboxSkillExecutor.execute_snippet(code, context={"items": [1, 2, 3, 4, 5]})
    assert res["ok"] is True
    assert res["output"]["total"] == 30
    assert res["output"]["max_val"] == 5


def test_dynamic_skill_compilation_and_registration():
    print("\n== Test DynamicSkillManager: Génération et injection à chaud d'un @skill ==")
    reg = SkillRegistry()
    mgr = DynamicSkillManager(registry=reg)
    
    skill_code = """
def custom_math_skill(payload: dict) -> dict:
    numbers = payload.get("numbers", [])
    operation = payload.get("op", "sum")
    if operation == "sum":
        return {"result": sum(numbers)}
    elif operation == "product":
        prod = 1
        for n in numbers:
            prod *= n
        return {"result": prod}
    return {"error": "unknown operation"}
"""
    
    # Test avec assertion interne
    res = mgr.register_code_skill(
        skill_name="custom_math",
        function_code=skill_code,
        test_payload={"numbers": [2, 3, 4], "op": "product"},
    )
    
    assert res["ok"] is True
    assert "custom_math" in reg.skills
    
    # Exécution via le registre
    fn = reg.get("custom_math")
    output = fn({"numbers": [10, 20, 30], "op": "sum"})
    assert output["result"] == 60


async def test_sandbox_mesh_skills():
    print("\n== Test Sandbox Mesh Skills ==")
    skills = get_sandbox_skills()
    
    # 1. Exécution de snippet
    exec_res = await skills["sandbox_execute_code"]({
        "code": "result = math.factorial(5)",
    })
    assert exec_res["ok"] is True
    assert exec_res["output"]["result"] == 120
