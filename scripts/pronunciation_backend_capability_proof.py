from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.services.azure_pronunciation_provider import (
    AzurePronunciationBackendConfig,
    AzurePronunciationBackendError,
    AzurePronunciationProvider,
    VOICE_B,
    build_inline_phoneme_ssml,
)
from app.services.pronunciation_service import provider_capabilities


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)

    import edge_tts
    edge=provider_capabilities("edge-tts",provider_version=getattr(edge_tts,"__version__","7.2.8"),voice=VOICE_B)
    edge_result={
        "backend":"edge-tts",
        "voice":VOICE_B,
        "provider_version":edge.provider_version,
        "PTBR_SSML_PHONEME_SUPPORTED":"YES" if edge.supports_ssml and edge.supports_phoneme else "NO",
        "PTBR_CUSTOM_LEXICON_SUPPORTED":"YES" if edge.supports_custom_lexicon else "NO",
        "VOICE_B_PHONEME_CONTROL_SUPPORTED":"YES" if edge.supports_phoneme else "NO",
        "reason":"edge-tts current service contract does not accept arbitrary custom SSML; production can control text/rate/volume/pitch but not phoneme/PLS.",
    }

    # Azure Speech is a separate, explicit candidate backend. Microsoft documents
    # SSML phoneme/custom lexicon and pt-BR IPA support; it is not silently treated
    # as production-capable until this exact Voice B succeeds in a live request.
    live_configured=bool(os.environ.get("AZURE_SPEECH_KEY","").strip() and os.environ.get("AZURE_SPEECH_REGION","").strip())
    azure={
        "backend":"azure-speech",
        "voice":VOICE_B,
        "AZURE_SPEECH_SERVICE_PHONEME_DOCUMENTED":"YES",
        "AZURE_SPEECH_SERVICE_CUSTOM_LEXICON_DOCUMENTED":"YES",
        "PTBR_IPA_PHONESET_DOCUMENTED":"YES",
        "VOICE_B_LISTED_BY_AZURE":"YES",
        "AZURE_SPEECH_BACKEND_IMPLEMENTED":"YES",
        "AZURE_SPEECH_RUNTIME_CONFIGURED":"YES" if live_configured else "NO",
        "AZURE_SPEECH_LIVE_PROOF":"PENDING",
    }
    ssml=build_inline_phoneme_ssml(
        context_before="O estado de ",
        canonical_term="Leonida",
        context_after=" vai muito além de Vice City.",
        ipa="leˈonidɐ",
    )
    (args.output_dir/"leonida-inline-phoneme.ssml").write_text(ssml,encoding="utf-8")

    if live_configured:
        try:
            config=AzurePronunciationBackendConfig.from_env()
            provider=AzurePronunciationProvider(config)
            output=args.output_dir/"leonida-azure-phoneme.wav"
            provider.synthesize_ssml(ssml,output)
            azure["AZURE_SPEECH_LIVE_PROOF"]="PASS"
            azure["VOICE_B_AZURE_PHONEME_LIVE"]="PASS"
        except Exception as exc:
            azure["AZURE_SPEECH_LIVE_PROOF"]="FAIL"
            azure["VOICE_B_AZURE_PHONEME_LIVE"]="FAIL"
            azure["live_error"]=type(exc).__name__+": "+str(exc)
    else:
        azure["AZURE_SPEECH_LIVE_PROOF"]="BLOCKED_MISSING_RUNTIME_CREDENTIALS"
        azure["VOICE_B_AZURE_PHONEME_LIVE"]="UNPROVEN"

    result={
        "status":"PASS",
        "CURRENT_PRODUCTION_BACKEND":"edge-tts",
        **edge_result,
        "AZURE_CANDIDATE":azure,
        "PHONEME_CONTROL_BACKEND":(
            "AZURE_SPEECH_CANDIDATE_LIVE_PROVEN"
            if azure["AZURE_SPEECH_LIVE_PROOF"]=="PASS"
            else "NONE_CURRENTLY_PROVEN_FOR_PRODUCTION"
        ),
        "ORTHOGRAPHIC_ALIAS_IS_ACOUSTIC_CONTROL":False,
        "PRODUCTION_BACKEND_PROMOTION":"BLOCKED_PENDING_LIVE_VOICE_B_AND_HUMAN_AUDIO_PROOF",
        "LEONIDA_PRONUNCIATION":"FAIL",
        "ROCKSTAR_PRONUNCIATION":"FAIL",
        "GLOBAL_PRONUNCIATION_STATUS":"FAIL",
        "HUMAN_VOICE_REVIEW":"REJECTED",
        "FULL_RENDER_AUTHORIZED":"NO",
    }
    (args.output_dir/"pronunciation-backend-capability.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    for key in (
        "CURRENT_PRODUCTION_BACKEND","PTBR_SSML_PHONEME_SUPPORTED",
        "PTBR_CUSTOM_LEXICON_SUPPORTED","VOICE_B_PHONEME_CONTROL_SUPPORTED",
        "PHONEME_CONTROL_BACKEND"
    ):
        print(f"{key}={result[key]}")
    print("AZURE_SPEECH_LIVE_PROOF="+azure["AZURE_SPEECH_LIVE_PROOF"])
    print("FULL_RENDER_AUTHORIZED=NO")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
