from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
from xml.sax.saxutils import escape, quoteattr

PRONUNCIATION_LAYER_VERSION = "br-no-gta-pronunciation/v5"
DEFAULT_LOCALE = "pt-BR"
DEFAULT_VOICE = "pt-BR-ThalitaMultilingualNeural"
LEXICON_PATH = Path(__file__).resolve().parents[2] / "config" / "pronunciation_lexicon.json"
_TRIVIA_RE = re.compile(r"^[\s.,!?;:—–-]*$")
_AUTODETECT_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")
_AUTODETECT_EXCLUDE = {"BR", "PT", "SP", "RJ"}

class PronunciationError(ValueError):
    pass

@dataclass(frozen=True)
class ProviderCapabilities:
    provider_id: str
    provider_version: str | None
    supports_language_spans: bool
    supports_isolated_multilingual_chunks: bool
    supports_ssml: bool
    supports_phoneme: bool
    supports_custom_lexicon: bool
    supports_same_voice_multilingual: bool
    supports_word_boundaries: bool
    locale_enforcement: str
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class SynthesisSpan:
    start: int
    end: int
    text: str
    locale: str
    strategy: str
    synthesis_text: str
    source: str
    pronunciation_identity: str | None = None
    confidence: float | None = None
    critical: bool = False
    target_ipa: str | None = None
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class SynthesisPlan:
    canonical_text: str
    default_locale: str
    voice: str
    resolver_version: str
    lexicon_version: str
    spans: tuple[SynthesisSpan, ...]
    lexicon_hits: tuple[str, ...]
    explicit_span_count: int
    detected_span_count: int
    resolution_wall_clock_seconds: float
    @property
    def foreign_span_count(self) -> int:
        return sum(1 for span in self.spans if span.locale != self.default_locale)
    @property
    def rendered_text(self) -> str:
        return "".join(span.synthesis_text for span in self.spans)
    @property
    def canonical_text_preserved(self) -> bool:
        return "".join(span.text for span in self.spans) == self.canonical_text
    @property
    def human_approval_required(self) -> bool:
        return any(span.critical for span in self.spans)
    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_text": self.canonical_text,
            "default_locale": self.default_locale,
            "voice": self.voice,
            "resolver_version": self.resolver_version,
            "lexicon_version": self.lexicon_version,
            "spans": [span.to_dict() for span in self.spans],
            "lexicon_hits": list(self.lexicon_hits),
            "explicit_span_count": self.explicit_span_count,
            "detected_span_count": self.detected_span_count,
            "foreign_span_count": self.foreign_span_count,
            "canonical_text_preserved": self.canonical_text_preserved,
            "human_approval_required": self.human_approval_required,
            "resolution_wall_clock_seconds": self.resolution_wall_clock_seconds,
        }

def load_pronunciation_lexicon(path: Path | None = None) -> dict[str, Any]:
    payload = json.loads((path or LEXICON_PATH).read_text(encoding="utf-8"))
    if payload.get("schema") != "br-no-gta-pronunciation-lexicon/v1":
        raise PronunciationError("unsupported pronunciation lexicon schema")
    if not payload.get("version") or not isinstance(payload.get("entries"), list):
        raise PronunciationError("pronunciation lexicon is incomplete")
    seen=set()
    for entry in payload["entries"]:
        required=("identity","term","locale","strategy")
        if not isinstance(entry,dict) or any(not str(entry.get(k) or "").strip() for k in required):
            raise PronunciationError("pronunciation lexicon entry missing required fields")
        if entry["identity"] in seen:
            raise PronunciationError("duplicate pronunciation identity")
        seen.add(entry["identity"])
    return payload

def pronunciation_lexicon_version(path: Path | None = None) -> str:
    return str(load_pronunciation_lexicon(path)["version"])

def canonical_lexicon_entries(path: Path | None = None) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in load_pronunciation_lexicon(path)["entries"])

def _match_lexicon(text: str, lexicon: dict[str, Any]) -> list[dict[str, Any]]:
    out=[]
    for entry in lexicon["entries"]:
        variants=[entry["term"],*(entry.get("aliases") or [])]
        for variant in dict.fromkeys(str(v) for v in variants if v):
            pattern=re.compile(r"(?<!\w)"+re.escape(variant)+r"(?!\w)",re.IGNORECASE)
            for m in pattern.finditer(text):
                out.append({
                    "start":m.start(),"end":m.end(),"locale":entry["locale"],
                    "strategy":entry["strategy"],"source":"lexicon",
                    "pronunciation_identity":entry["identity"],
                    "synthesis_text":entry.get("synthesis_text"),
                    "confidence":1.0,"critical":bool(entry.get("critical")),
                    "target_ipa":entry.get("target_ipa"),"priority":0,
                })
    return out

def _match_explicit(text: str, explicit_spans: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out=[]
    for item in explicit_spans or []:
        try:
            start,end=int(item["start"]),int(item["end"])
        except (KeyError,TypeError,ValueError) as exc:
            raise PronunciationError("explicit pronunciation span requires integer start/end") from exc
        if start<0 or end<=start or end>len(text):
            raise PronunciationError("explicit pronunciation span bounds invalid")
        selected=text[start:end]
        if item.get("text") is not None and str(item["text"])!=selected:
            raise PronunciationError("explicit pronunciation span text does not match canonical text")
        locale=str(item.get("locale") or "").strip()
        if not locale:
            raise PronunciationError("explicit pronunciation span locale required")
        if selected.casefold() != "vice city":
            locale=DEFAULT_LOCALE
        out.append({
            "start":start,"end":end,"locale":locale,
            "strategy":str(item.get("strategy") or "explicit-locale"),
            "source":"explicit","pronunciation_identity":item.get("pronunciation_identity"),
            "synthesis_text":item.get("synthesis_text"),"confidence":1.0,
            "critical":bool(item.get("critical")),"target_ipa":item.get("target_ipa"),"priority":1,
        })
    return out

def _conservative_autodetect(text: str) -> list[dict[str, Any]]:
    """Disabled by human policy: PT-BR remains canonical unless explicitly approved."""
    return []

def _select_non_overlapping(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted=[]
    for candidate in sorted(candidates,key=lambda x:(int(x["priority"]),-(int(x["end"])-int(x["start"])),int(x["start"]))):
        if any(not(candidate["end"]<=item["start"] or candidate["start"]>=item["end"]) for item in accepted):
            continue
        accepted.append(candidate)
    return sorted(accepted,key=lambda x:int(x["start"]))

def _append_span(spans: list[SynthesisSpan], span: SynthesisSpan) -> None:
    if not span.text:
        return
    if spans and _TRIVIA_RE.fullmatch(span.text):
        prev=spans[-1]
        spans[-1]=replace(prev,end=span.end,text=prev.text+span.text,synthesis_text=prev.synthesis_text+span.synthesis_text)
        return
    if spans:
        prev=spans[-1]
        if prev.end==span.start and prev.locale==span.locale and prev.strategy==span.strategy and prev.source==span.source and prev.pronunciation_identity==span.pronunciation_identity and prev.critical==span.critical:
            spans[-1]=replace(prev,end=span.end,text=prev.text+span.text,synthesis_text=prev.synthesis_text+span.synthesis_text)
            return
    spans.append(span)

def resolve_synthesis_plan(
    text: str,
    *,
    default_locale: str = DEFAULT_LOCALE,
    voice: str = DEFAULT_VOICE,
    explicit_spans: list[dict[str, Any]] | None = None,
    lexicon_path: Path | None = None,
    enable_conservative_detection: bool = False,
) -> SynthesisPlan:
    started=time.monotonic()
    if not isinstance(text,str) or not text:
        raise PronunciationError("canonical text is required")
    lexicon=load_pronunciation_lexicon(lexicon_path)
    candidates=_match_explicit(text,explicit_spans)+_match_lexicon(text,lexicon)
    if enable_conservative_detection:
        candidates+=_conservative_autodetect(text)
    selected=_select_non_overlapping(candidates)
    spans=[]
    cursor=0
    for item in selected:
        start,end=int(item["start"]),int(item["end"])
        if start>cursor:
            native=text[cursor:start]
            _append_span(spans,SynthesisSpan(cursor,start,native,default_locale,"native",native,"fallback"))
        canonical=text[start:end]
        _append_span(spans,SynthesisSpan(
            start,end,canonical,str(item["locale"]),str(item["strategy"]),
            str(item.get("synthesis_text") or canonical),str(item["source"]),
            str(item["pronunciation_identity"]) if item.get("pronunciation_identity") else None,
            float(item["confidence"]) if item.get("confidence") is not None else None,
            bool(item.get("critical")),
            str(item["target_ipa"]) if item.get("target_ipa") else None,
        ))
        cursor=end
    if cursor<len(text):
        native=text[cursor:]
        _append_span(spans,SynthesisSpan(cursor,len(text),native,default_locale,"native",native,"fallback"))
    if not spans:
        spans=[SynthesisSpan(0,len(text),text,default_locale,"native",text,"fallback")]
    if len(spans)>1 and _TRIVIA_RE.fullmatch(spans[0].text):
        trivia=spans.pop(0)
        first=spans[0]
        spans[0]=replace(first,start=trivia.start,text=trivia.text+first.text,synthesis_text=trivia.synthesis_text+first.synthesis_text)
    plan=SynthesisPlan(
        canonical_text=text,default_locale=default_locale,voice=voice,
        resolver_version=PRONUNCIATION_LAYER_VERSION,lexicon_version=str(lexicon["version"]),
        spans=tuple(spans),
        lexicon_hits=tuple(dict.fromkeys(span.pronunciation_identity for span in spans if span.source=="lexicon" and span.pronunciation_identity)),
        explicit_span_count=sum(1 for span in spans if span.source=="explicit"),
        detected_span_count=sum(1 for span in spans if span.source=="detector"),
        resolution_wall_clock_seconds=time.monotonic()-started,
    )
    if not plan.canonical_text_preserved:
        raise PronunciationError("synthesis plan mutated canonical text")
    return plan

def synthesis_plan_from_dict(payload: dict[str, Any]) -> SynthesisPlan:
    spans=tuple(SynthesisSpan(
        start=int(item["start"]),end=int(item["end"]),text=str(item["text"]),
        locale=str(item["locale"]),strategy=str(item["strategy"]),
        synthesis_text=str(item["synthesis_text"]),source=str(item["source"]),
        pronunciation_identity=str(item["pronunciation_identity"]) if item.get("pronunciation_identity") else None,
        confidence=float(item["confidence"]) if item.get("confidence") is not None else None,
        critical=bool(item.get("critical")),target_ipa=str(item["target_ipa"]) if item.get("target_ipa") else None,
    ) for item in payload.get("spans") or [])
    plan=SynthesisPlan(
        canonical_text=str(payload.get("canonical_text") or ""),
        default_locale=str(payload.get("default_locale") or DEFAULT_LOCALE),
        voice=str(payload.get("voice") or DEFAULT_VOICE),
        resolver_version=str(payload.get("resolver_version") or PRONUNCIATION_LAYER_VERSION),
        lexicon_version=str(payload.get("lexicon_version") or ""),
        spans=spans,lexicon_hits=tuple(str(x) for x in payload.get("lexicon_hits") or []),
        explicit_span_count=int(payload.get("explicit_span_count") or 0),
        detected_span_count=int(payload.get("detected_span_count") or 0),
        resolution_wall_clock_seconds=float(payload.get("resolution_wall_clock_seconds") or 0.0),
    )
    if not plan.canonical_text or not plan.spans or not plan.canonical_text_preserved:
        raise PronunciationError("serialized synthesis plan is invalid")
    return plan

def provider_capabilities(provider_id: str, *, provider_version: str | None = None, voice: str = DEFAULT_VOICE) -> ProviderCapabilities:
    normalized=provider_id.strip().lower()
    multilingual="multilingual" in voice.lower()
    if normalized=="edge-tts":
        return ProviderCapabilities("edge-tts",provider_version,False,multilingual,False,False,False,multilingual,True,"auto-detect-per-isolated-chunk")
    if normalized in {"azure-speech","azure-cognitive-speech"}:
        return ProviderCapabilities("azure-speech",provider_version,True,True,True,not multilingual,not multilingual,multilingual,True,"ssml-lang")
    return ProviderCapabilities(provider_id,provider_version,False,False,False,False,False,False,False,"none")

def validate_provider_plan(plan: SynthesisPlan, capabilities: ProviderCapabilities) -> None:
    if not plan.canonical_text_preserved:
        raise PronunciationError("canonical text mutation is forbidden")
    if any(span.strategy=="phoneme" for span in plan.spans) and not capabilities.supports_phoneme:
        raise PronunciationError("provider/voice does not support phoneme strategy")
    if plan.foreign_span_count and not (
        capabilities.supports_language_spans or
        (capabilities.supports_isolated_multilingual_chunks and capabilities.supports_same_voice_multilingual)
    ):
        raise PronunciationError("provider cannot preserve requested multilingual pronunciation")

def synthesis_plan_cache_payload(plan: SynthesisPlan) -> dict[str, Any]:
    """Deterministic synthesis identity; runtime telemetry is intentionally excluded."""
    return {
        "canonical_text":plan.canonical_text,
        "default_locale":plan.default_locale,
        "voice":plan.voice,
        "resolver_version":plan.resolver_version,
        "lexicon_version":plan.lexicon_version,
        "spans":[span.to_dict() for span in plan.spans],
        "lexicon_hits":list(plan.lexicon_hits),
        "explicit_span_count":plan.explicit_span_count,
        "detected_span_count":plan.detected_span_count,
        "foreign_span_count":plan.foreign_span_count,
        "canonical_text_preserved":plan.canonical_text_preserved,
        "human_approval_required":plan.human_approval_required,
    }

def pronunciation_cache_identity(plan: SynthesisPlan, *, provider_id: str, provider_version: str, voice: str, rate: str, pitch: str = "+0Hz") -> dict[str, Any]:
    payload={
        **synthesis_plan_cache_payload(plan),
        "provider":provider_id,"provider_version":provider_version,"voice":voice,"rate":rate,"pitch":pitch,
    }
    canonical=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return {**payload,"sha256":hashlib.sha256(canonical.encode("utf-8")).hexdigest()}

def build_azure_ssml(plan: SynthesisPlan, *, voice: str = DEFAULT_VOICE) -> str:
    caps=provider_capabilities("azure-speech",voice=voice)
    validate_provider_plan(plan,caps)
    pieces=[]
    for span in plan.spans:
        rendered=escape(span.synthesis_text)
        pieces.append(f"<lang xml:lang={quoteattr(span.locale)}>{rendered}</lang>" if span.locale!=plan.default_locale else rendered)
    return f"<speak version=\"1.0\" xml:lang={quoteattr(plan.default_locale)}><voice name={quoteattr(voice)}>{''.join(pieces)}</voice></speak>"

def _edge_synthesis_groups(plan: SynthesisPlan) -> list[dict[str, Any]]:
    """
    Preserve natural sentence prosody by avoiding TTS resets at same-locale alias
    boundaries. Edge only needs a separate request when the locale actually changes.
    """
    groups: list[dict[str, Any]] = []
    for index, span in enumerate(plan.spans):
        if groups and groups[-1]["locale"] == span.locale:
            groups[-1]["synthesis_text"] += span.synthesis_text
            groups[-1]["span_indexes"].append(index)
            if span.pronunciation_identity:
                groups[-1]["pronunciation_identities"].append(span.pronunciation_identity)
            continue
        groups.append({
            "locale": span.locale,
            "synthesis_text": span.synthesis_text,
            "span_indexes": [index],
            "pronunciation_identities": (
                [span.pronunciation_identity] if span.pronunciation_identity else []
            ),
        })
    return groups


_EDGE_INTER_GROUP_LEADING_PAD_SECONDS = 0.100
_EDGE_INTER_GROUP_TRAILING_PAD_SECONDS = 0.140
_EDGE_INTER_GROUP_CROSSFADE_SECONDS = 0.060


def _edge_trim_window(
    word_boundaries: list[dict[str, Any]],
    duration: float,
    *,
    trim_leading: bool,
    trim_trailing: bool,
) -> tuple[float, float]:
    if not word_boundaries:
        return 0.0, duration
    first=min(float(item["offset_seconds"]) for item in word_boundaries)
    last=max(
        float(item["offset_seconds"])+float(item["duration_seconds"])
        for item in word_boundaries
    )
    start=(
        max(0.0, first-_EDGE_INTER_GROUP_LEADING_PAD_SECONDS)
        if trim_leading else 0.0
    )
    end=(
        min(duration, last+_EDGE_INTER_GROUP_TRAILING_PAD_SECONDS)
        if trim_trailing else duration
    )
    if end<=start:
        raise PronunciationError("invalid pronunciation chunk trim window")
    return start,end


def _probe_duration(path: Path) -> float:
    result=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(path)],capture_output=True,text=True,timeout=120)
    if result.returncode!=0:
        raise PronunciationError("ffprobe failed for pronunciation chunk")
    try:
        value=float(result.stdout.strip())
    except (TypeError,ValueError) as exc:
        raise PronunciationError("pronunciation chunk duration invalid") from exc
    if value<=0:
        raise PronunciationError("pronunciation chunk duration must be positive")
    return value

async def synthesize_edge_plan(plan: SynthesisPlan, *, voice: str, rate: str, pitch: str = "+0Hz", output: Path) -> dict[str, Any]:
    import edge_tts
    caps=provider_capabilities("edge-tts",provider_version="7.2.8",voice=voice)
    validate_provider_plan(plan,caps)
    output.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    rows=[]
    with tempfile.TemporaryDirectory(prefix="pronunciation-",dir=str(output.parent)) as tmp:
        root=Path(tmp)
        groups=_edge_synthesis_groups(plan)
        trim_windows=[]
        local_timings=[]
        for index,group in enumerate(groups):
            chunk=root/f"{index:03d}.mp3"
            communicator=edge_tts.Communicate(
                text=group["synthesis_text"],
                voice=voice,
                rate=rate,
                pitch=pitch,
                volume="+0%",
                boundary="WordBoundary",
            )
            local=[]
            with chunk.open("wb") as stream:
                async for event in communicator.stream():
                    if event.get("type")=="audio":
                        stream.write(event.get("data") or b"")
                    elif event.get("type")=="WordBoundary":
                        local.append({
                            "type":"word","text":str(event.get("text") or ""),
                            "offset_seconds":float(event.get("offset") or 0)/10_000_000.0,
                            "duration_seconds":float(event.get("duration") or 0)/10_000_000.0,
                        })
            if not chunk.is_file() or chunk.stat().st_size<=0:
                raise PronunciationError("Edge TTS returned empty pronunciation chunk")
            raw_duration=_probe_duration(chunk)
            trim_start,trim_end=_edge_trim_window(
                local,
                raw_duration,
                trim_leading=index>0,
                trim_trailing=index<len(groups)-1,
            )
            effective_duration=trim_end-trim_start
            trim_windows.append((trim_start,trim_end))
            local_timings.append(local)
            rows.append({
                "index":index,
                "locale":group["locale"],
                "span_indexes":list(group["span_indexes"]),
                "pronunciation_identities":list(group["pronunciation_identities"]),
                "raw_duration_seconds":raw_duration,
                "trim_start_seconds":trim_start,
                "trim_end_seconds":trim_end,
                "duration_seconds":effective_duration,
                "trimmed_padding_seconds":raw_duration-effective_duration,
                "bytes":chunk.stat().st_size,
            })

        join_durations=[]
        for index in range(1,len(rows)):
            join_durations.append(min(
                _EDGE_INTER_GROUP_CROSSFADE_SECONDS,
                float(rows[index-1]["duration_seconds"])/4.0,
                float(rows[index]["duration_seconds"])/4.0,
            ))

        timing=[]
        cumulative=0.0
        for index,(row,local,(trim_start,trim_end)) in enumerate(zip(rows,local_timings,trim_windows)):
            if index>0:
                cumulative=max(0.0,cumulative-join_durations[index-1])
            group_start=cumulative
            for item in local:
                shifted=max(0.0,float(item["offset_seconds"])-trim_start)
                timing.append({
                    **item,
                    "offset_seconds":group_start+shifted,
                })
            row["output_start_seconds"]=group_start
            cumulative=group_start+float(row["duration_seconds"])

        ffmpeg_command=[
            "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
        ]
        for idx in range(len(groups)):
            ffmpeg_command.extend(["-i",str(root/f"{idx:03d}.mp3")])
        filters=[]
        for idx,(trim_start,trim_end) in enumerate(trim_windows):
            filters.append(
                f"[{idx}:a]atrim=start={trim_start:.6f}:end={trim_end:.6f},"
                f"asetpts=PTS-STARTPTS[a{idx}]"
            )
        if len(groups)==1:
            filters.append("[a0]anull[outa]")
        else:
            current="[a0]"
            for idx in range(1,len(groups)):
                target="[outa]" if idx==len(groups)-1 else f"[x{idx}]"
                filters.append(
                    f"{current}[a{idx}]acrossfade=d={join_durations[idx-1]:.6f}:"
                    f"c1=tri:c2=tri{target}"
                )
                current=target
        ffmpeg_command.extend([
            "-filter_complex",";".join(filters),
            "-map","[outa]",
            "-c:a","libmp3lame","-b:a","64k",str(output),
        ])
        result=subprocess.run(
            ffmpeg_command,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode!=0:
            raise PronunciationError("pronunciation chunk concat failed")
    if not output.is_file() or output.stat().st_size<=0:
        raise PronunciationError("pronunciation synthesis output missing")
    return {
        "status":"PASS","output":str(output),"bytes_written":output.stat().st_size,
        "wall_clock_seconds":time.monotonic()-started,"external_calls":len(groups),
        "span_count":len(plan.spans),"synthesis_group_count":len(groups),
        "foreign_span_count":plan.foreign_span_count,
        "timing":timing,"chunks":rows,"provider_capabilities":caps.to_dict(),
        "canonical_text_preserved":plan.canonical_text_preserved,
        "join_policy":"same-locale-coalesced-safe-margin-acrossfade",
        "inserted_silence_seconds":0.0,
        "trimmed_padding_seconds":sum(float(item["trimmed_padding_seconds"]) for item in rows),
        "inter_group_leading_pad_seconds":_EDGE_INTER_GROUP_LEADING_PAD_SECONDS,
        "inter_group_trailing_pad_seconds":_EDGE_INTER_GROUP_TRAILING_PAD_SECONDS,
        "crossfade_seconds_per_join":join_durations,
        "crossfade_seconds_total":sum(join_durations),
        "prosody_continuity_policy":"same-locale aliases stay in one PT-BR request; only Vice City may isolate en-US, with safe word margins and silence-only crossfade",
    }
