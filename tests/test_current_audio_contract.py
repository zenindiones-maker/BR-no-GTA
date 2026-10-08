from app.services.current_audio_contract_service import current_audio_contract
from app.workers.professional_audiovisual_worker import _words


def test_current_audio_contract_is_owner_only_and_fail_closed_until_private_reference():
    c = current_audio_contract()
    assert c["OFFICIAL_VOICE"] == "BR_OWNER_V1"
    assert c["VOICE_SHORT_NAME"] == "BR_OWNER_V1"
    assert c["VOICE_IDENTITY_ID"] == "BR_OWNER_V1"
    assert c["VOICE_POLICY"] == "OWNER_VOICE_ONLY"
    assert c["ACTIVE_VOICE_IDENTITIES"] == ["BR_OWNER_V1"]
    assert c["SINGLE_VOICE_ONLY"] is True
    assert c["ALTERNATIVE_VOICE_CASTING"] == "DISABLED"
    assert c["SPOKEN_BRANDING_CONTRACT"] == "br-no-gta-spoken-branding/v5-owner-only"
    assert c["OPENING_REFERENCE"] is None
    assert c["OPENING_TAKE"] == "BR_OWNER_V1-dynamic"
    assert c["OPENING_RATE"] == "+0%"
    assert c["OPENING_PITCH"] == "+0Hz"
    assert c["CLOSING_ASSET"] is None
    assert c["CLOSING_TAKE"] == "BR_OWNER_V1-dynamic"
    assert c["CLOSING_ASSET_POLICY"] == "SYNTHESIZE_WITH_OWNER_IDENTITY"
    assert c["OWNER_REFERENCE_SOURCE"] == "TELEGRAM"
    assert c["OWNER_REFERENCE_READY"] is False
    assert c["DEFAULT_NARRATION_LOCALE"] == "pt-BR"
    assert c["ONLY_FORCED_EN_US_TERM"] is None
    assert c["GTA_6_SYNTHESIS"] == "Gê Tê A seis"
    assert c["OFFICIAL_VOICE"] == "BR_OWNER_V1"
    assert c["VICE_CITY_LOCALE"] == "pt-BR"
    assert c["VICE_CITY_TARGET_IPA"] == "vaɪs ˈsɪti"
    assert c["LUCIA_SYNTHESIS_ALIAS"] == "Lucía"
    assert len(c["CURRENT_AUDIO_CONTRACT_FINGERPRINT"]) == 64


def test_approved_product_script_word_count_remains_nonempty():
    assert len(_words("GTA 6 em Vice City continua sendo o mesmo texto editorial aprovado.")) > 0
