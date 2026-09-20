from app.services.current_audio_contract_service import current_audio_contract
from app.workers.professional_audiovisual_worker import _words


def test_current_audio_contract_is_human_approved_voice_b():
    c=current_audio_contract()
    assert c["OFFICIAL_VOICE"]=="Voice B"
    assert c["VOICE_SHORT_NAME"]=="pt-BR-ThalitaMultilingualNeural"
    assert c["SINGLE_VOICE_ONLY"] is True
    assert c["ALTERNATIVE_VOICE_CASTING"]=="DISABLED"
    assert c["SPOKEN_BRANDING_CONTRACT"]=="br-no-gta-spoken-branding/v3"
    assert c["OPENING_REFERENCE"]=="I-opening-fluid-2.mp3"
    assert c["OPENING_TAKE"]=="take-2"
    assert c["OPENING_RATE"]=="+3%"
    assert c["OPENING_PITCH"]=="+1Hz"
    assert c["CLOSING_ASSET"]=="G-brand-mixed"
    assert c["APPROVED_G_SHA256"]=="9e2e7a2d9717f460dd45cf0d07e96a4596e4f61372c6d87028b8809a052c59ca"
    assert c["DEFAULT_NARRATION_LOCALE"]=="pt-BR"
    assert c["ONLY_FORCED_EN_US_TERM"]=="Vice City"
    assert c["GTA_6_SYNTHESIS"]=="gê tê á seis"
    assert c["VICE_CITY_LOCALE"]=="en-US"
    assert c["VICE_CITY_TARGET_IPA"]=="vaɪs ˈsɪti"
    assert c["PRONUNCIATION_LEXICON_VERSION"]=="2026.09.19.4"
    assert len(c["CURRENT_AUDIO_CONTRACT_FINGERPRINT"])==64


def test_approved_product_script_word_count_remains_nonempty():
    assert len(_words("GTA 6 em Vice City continua sendo o mesmo texto editorial aprovado.")) > 0
