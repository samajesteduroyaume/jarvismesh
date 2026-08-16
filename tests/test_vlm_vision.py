"""
Tests pour le moteur Vision VLM et l'analyse multimodale (jarvismesh.vlm_engine).
"""
import base64
import pytest
from jarvismesh.vlm_engine import VLMModelManager, get_vlm_skills


def test_vlm_image_analysis_formats():
    print("\n== Test VLM: Analyse d'image raw bytes et base64 ==")
    vlm = VLMModelManager()
    
    # 1. Image factice PNG (header PNG standard)
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    res_bytes = vlm.analyze_image(fake_png, prompt="Que représente ce diagramme ?")
    
    assert res_bytes["ok"] is True
    assert res_bytes["image_meta"]["format"] == "PNG"
    assert "diagramme" in res_bytes["description"]
    
    # 2. Image Base64 Data URI
    b64_str = "data:image/png;base64," + base64.b64encode(fake_png).decode("ascii")
    res_b64 = vlm.analyze_image(b64_str, prompt="Audit visuel de la topologie")
    assert res_b64["ok"] is True
    assert res_b64["image_meta"]["source"] == "base64_data_uri"


async def test_vlm_mesh_skill():
    print("\n== Test VLM Skill: Ingestion via compétence mesh ==")
    skills = get_vlm_skills()
    
    fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
    b64 = base64.b64encode(fake_jpeg).decode("ascii")
    
    res = await skills["vision_analyze"]({
        "image": b64,
        "prompt": "Analyse le schéma d'architecture réseau",
    })
    
    assert res["ok"] is True
    assert res["image_meta"]["format"] == "JPEG"
    assert "schéma d'architecture" in res["description"]
