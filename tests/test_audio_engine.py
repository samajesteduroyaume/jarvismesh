"""
Tests pour le moteur audio et la transcription vocale (jarvismesh.audio_engine).
"""
import base64
import pytest
from jarvismesh.audio_engine import AudioTranscriber, get_audio_skills


def test_audio_transcriber_formats():
    print("\n== Test Audio: Détection des formats WAV / MP3 ==")
    transcriber = AudioTranscriber()
    
    # 1. Fake WAV RIFF header
    fake_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    res = transcriber.transcribe(fake_wav, language="fr")
    
    assert res["ok"] is True
    assert res["audio_meta"]["format"] == "WAV"
    assert res["language"] == "fr"
    assert len(res["segments"]) >= 1


async def test_audio_mesh_skill():
    print("\n== Test Audio Skill: Compétence audio_transcribe ==")
    skills = get_audio_skills()
    
    fake_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    b64 = "data:audio/wav;base64," + base64.b64encode(fake_wav).decode("ascii")
    
    res = await skills["audio_transcribe"]({
        "audio": b64,
        "language": "en",
    })
    
    assert res["ok"] is True
    assert res["language"] == "en"
    assert res["audio_meta"]["source"] == "base64_data_uri"
