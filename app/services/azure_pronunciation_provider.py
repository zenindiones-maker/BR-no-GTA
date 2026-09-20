from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

VOICE_B="pt-BR-ThalitaMultilingualNeural"
DEFAULT_LOCALE="pt-BR"


class AzurePronunciationBackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class AzurePronunciationBackendConfig:
    subscription_key: str
    region: str
    voice: str = VOICE_B
    locale: str = DEFAULT_LOCALE

    @classmethod
    def from_env(cls) -> "AzurePronunciationBackendConfig":
        key=os.environ.get("AZURE_SPEECH_KEY","").strip()
        region=os.environ.get("AZURE_SPEECH_REGION","").strip()
        if not key or not region:
            raise AzurePronunciationBackendError(
                "AZURE_SPEECH_KEY/AZURE_SPEECH_REGION are required for live Azure phoneme synthesis"
            )
        return cls(subscription_key=key,region=region)


def build_inline_phoneme_ssml(
    *,
    context_before: str,
    canonical_term: str,
    context_after: str,
    ipa: str,
    voice: str = VOICE_B,
    locale: str = DEFAULT_LOCALE,
    rate: str = "+3%",
    pitch: str = "+1Hz",
) -> str:
    if not canonical_term.strip() or not ipa.strip():
        raise AzurePronunciationBackendError("canonical term and IPA are required")
    body=(
        escape(context_before)
        + f"<phoneme alphabet=\"ipa\" ph={quoteattr(ipa)}>{escape(canonical_term)}</phoneme>"
        + escape(context_after)
    )
    return (
        f"<speak version=\"1.0\" xml:lang={quoteattr(locale)} "
        f"xmlns=\"http://www.w3.org/2001/10/synthesis\">"
        f"<voice name={quoteattr(voice)}>"
        f"<prosody rate={quoteattr(rate)} pitch={quoteattr(pitch)}>{body}</prosody>"
        "</voice></speak>"
    )


def build_custom_lexicon_ssml(
    *,
    text: str,
    lexicon_uri: str,
    voice: str = VOICE_B,
    locale: str = DEFAULT_LOCALE,
    rate: str = "+3%",
    pitch: str = "+1Hz",
) -> str:
    if not lexicon_uri.startswith(("https://","http://")):
        raise AzurePronunciationBackendError("custom lexicon URI must be publicly accessible")
    return (
        f"<speak version=\"1.0\" xml:lang={quoteattr(locale)} "
        f"xmlns=\"http://www.w3.org/2001/10/synthesis\">"
        f"<voice name={quoteattr(voice)}>"
        f"<lexicon uri={quoteattr(lexicon_uri)}/>"
        f"<prosody rate={quoteattr(rate)} pitch={quoteattr(pitch)}>{escape(text)}</prosody>"
        "</voice></speak>"
    )


class AzurePronunciationProvider:
    provider_id="azure-speech"
    provider_version="speech-sdk"
    supports_ssml=True
    supports_phoneme=True
    supports_custom_lexicon=True
    supports_ipa=True

    def __init__(self,config:AzurePronunciationBackendConfig):
        self.config=config

    def synthesize_ssml(self,ssml:str,output:Path)->dict[str,Any]:
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as exc:
            raise AzurePronunciationBackendError(
                "azure-cognitiveservices-speech is not installed"
            ) from exc
        output.parent.mkdir(parents=True,exist_ok=True)
        speech_config=speechsdk.SpeechConfig(
            subscription=self.config.subscription_key,
            region=self.config.region,
        )
        speech_config.speech_synthesis_voice_name=self.config.voice
        audio_config=speechsdk.audio.AudioOutputConfig(filename=str(output))
        synthesizer=speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        result=synthesizer.speak_ssml_async(ssml).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            details=speechsdk.SpeechSynthesisCancellationDetails.from_result(result)
            raise AzurePronunciationBackendError(
                f"Azure synthesis failed: {details.reason}: {details.error_details}"
            )
        if not output.is_file() or output.stat().st_size<=0:
            raise AzurePronunciationBackendError("Azure synthesis produced no audio")
        return {
            "status":"PASS",
            "provider":self.provider_id,
            "voice":self.config.voice,
            "locale":self.config.locale,
            "output":str(output),
            "bytes":output.stat().st_size,
        }
