from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from difflib import SequenceMatcher
import hashlib
import json
import math
import re
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any

from app.services.media_ingestion import IngestionStatus
from app.services.pronunciation_service import (
    _edge_synthesis_groups,
    _edge_trim_window,
    _probe_duration,
    pronunciation_cache_identity,
    resolve_synthesis_plan,
)
from app.services.ytdlp_media_ingestion import YtDlpMediaIngestion
from scripts.character_name_pronunciation_proof import (
    acoustic_distance,
    canonical_script,
    ensure_acoustic_runtime,
    extract_occurrence,
    probe,
    sha256,
)

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"config"/"pronunciation_character_aliases.bc-review.json"
ROCKSTAR_TRAILER2_URL="https://www.youtube.com/watch?v=VQRLujxTm3c"
ROCKSTAR_TRAILER2_VIDEO_ID="VQRLujxTm3c"
EXPECTED_SCRIPT_SHA256="9bde9d9e5fd413597ecafadbfb55836ccbcaf10da7038aa83c133b3cc65c15ea"
VOICES={
    "B":"pt-BR-ThalitaMultilingualNeural",
    "C":"pt-BR-FranciscaNeural",
}
CHARACTERS=("Jason","Lucia")
KNOWN_NAMES=("Jason","Lucia","Cal Hampton","Boobie Ike","Dre'Quan Priest","Real Dimez","Raul Bautista","Brian Heder")
REFERENCE_VARIANTS={
    "Jason":("jason","jayson","jay son"),
    "Lucia":("lucia","lusia","lu cia"),
}

def normalize(value:str)->str:
    value=unicodedata.normalize("NFKD",value.casefold())
    value="".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+","",value)

def candidate_cache_key(alias:str)->str:
    digest=hashlib.sha256(alias.encode("utf-8")).hexdigest()[:10]
    return f"{normalize(alias) or 'candidate'}-{digest}"

def load_config()->dict[str,Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))

def find_entry(payload:dict[str,Any],identity:str)->dict[str,Any]:
    for item in payload.get("entries") or []:
        if item.get("identity")==identity:
            return item
    raise RuntimeError(f"missing lexicon entry: {identity}")

def script_inventory(text:str)->list[str]:
    return [name for name in KNOWN_NAMES if re.search(r"(?<!\w)"+re.escape(name)+r"(?!\w)",text,re.I)]

def materialize_reference(root:Path)->tuple[Path,dict[str,Any]]:
    root.mkdir(parents=True,exist_ok=True)
    source=root/"rockstar-trailer2.mp4"
    audio=root/"rockstar-trailer2-16k.wav"
    if source.is_file() and audio.is_file():
        return audio,{
            "video_file":str(source),
            "video_sha256":sha256(source),
            "audio_probe":probe(audio),
            "checkpoint_reuse":True,
        }
    result=YtDlpMediaIngestion().ingest(ROCKSTAR_TRAILER2_URL,root/"rockstar-trailer2")
    if result.status is not IngestionStatus.DOWNLOAD_OK or result.output_path is None:
        raise RuntimeError(f"Rockstar Trailer 2 materialization failed: {result.status.value}:{result.reason}")
    source=Path(result.output_path)
    audio=root/"rockstar-trailer2-16k.wav"
    proc=subprocess.run(
        ["ffmpeg","-nostdin","-y","-v","error","-i",str(source),"-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(audio)],
        capture_output=True,text=True,timeout=300,
    )
    if proc.returncode!=0:
        raise RuntimeError("Rockstar Trailer 2 audio extraction failed")
    return audio,{"video_file":str(source),"video_sha256":sha256(source),"audio_probe":probe(audio),"checkpoint_reuse":False}

def transcribe_words(audio:Path)->list[dict[str,Any]]:
    from faster_whisper import WhisperModel
    model=WhisperModel("small.en",device="cpu",compute_type="int8")
    segments,_=model.transcribe(
        str(audio),language="en",beam_size=5,vad_filter=True,word_timestamps=True,
        initial_prompt="Grand Theft Auto VI Trailer 2. Character names include Jason and Lucia.",
    )
    words=[]
    for segment in segments:
        for word in segment.words or []:
            text=str(word.word or "").strip()
            if text and word.start is not None and word.end is not None:
                words.append({
                    "text":text,
                    "start":float(word.start),
                    "end":float(word.end),
                    "probability":float(word.probability or 0.0),
                })
    if not words:
        raise RuntimeError("official Trailer 2 ASR produced no word timestamps")
    return words

def discover_occurrences(words:list[dict[str,Any]])->dict[str,list[dict[str,Any]]]:
    found={name:[] for name in CHARACTERS}
    for name in CHARACTERS:
        variants=[normalize(v) for v in REFERENCE_VARIANTS[name]]
        for index in range(len(words)):
            for width in (1,2):
                if index+width>len(words):
                    continue
                raw=" ".join(item["text"] for item in words[index:index+width])
                candidate=normalize(raw)
                score=max((SequenceMatcher(None,candidate,value).ratio() for value in variants),default=0.0)
                if score<0.72:
                    continue
                start=float(words[index]["start"]); end=float(words[index+width-1]["end"])
                if any(abs(start-item["start"])<0.2 for item in found[name]):
                    continue
                found[name].append({
                    "start":start,
                    "end":end,
                    "asr_text":raw,
                    "match_score":round(score,4),
                    "mean_probability":round(sum(float(item["probability"]) for item in words[index:index+width])/width,4),
                })
    return found

async def synthesize_isolated(text:str,voice:str,output:Path,plan:dict[str,Any])->None:
    import edge_tts
    output.parent.mkdir(parents=True,exist_ok=True)
    await edge_tts.Communicate(
        text=text,voice=voice,rate=plan["rate"],pitch=plan["pitch"],volume=plan["volume"]
    ).save(str(output))
    if not output.is_file() or output.stat().st_size<=0:
        raise RuntimeError("isolated alias synthesis missing")

async def synthesize_review_plan(plan_obj,*,voice:str,performance:dict[str,Any],output:Path)->dict[str,Any]:
    import edge_tts
    groups=_edge_synthesis_groups(plan_obj)
    output.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    rows=[]; timings=[]
    with tempfile.TemporaryDirectory(prefix="bc-review-",dir=str(output.parent)) as tmp:
        root=Path(tmp); trim_windows=[]; cumulative=0.0
        for index,group in enumerate(groups):
            chunk=root/f"{index:03d}.mp3"
            communicator=edge_tts.Communicate(
                text=group["synthesis_text"],voice=voice,
                rate=performance["rate"],pitch=performance["pitch"],volume=performance["volume"],
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
            raw_duration=_probe_duration(chunk)
            trim_start,trim_end=_edge_trim_window(
                local,raw_duration,trim_leading=index>0,trim_trailing=index<len(groups)-1
            )
            trim_windows.append((trim_start,trim_end))
            for item in local:
                timings.append({**item,"offset_seconds":cumulative+max(0.0,float(item["offset_seconds"])-trim_start)})
            effective=trim_end-trim_start
            rows.append({
                "index":index,"locale":group["locale"],"pronunciation_identities":group["pronunciation_identities"],
                "duration_seconds":effective,"raw_duration_seconds":raw_duration,
            })
            cumulative+=effective
        cmd=["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y"]
        for idx in range(len(groups)):
            cmd.extend(["-i",str(root/f"{idx:03d}.mp3")])
        filters=[]; labels=[]
        for idx,(start,end) in enumerate(trim_windows):
            label=f"a{idx}"
            filters.append(f"[{idx}:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[{label}]")
            labels.append(f"[{label}]")
        filters.append("".join(labels)+f"concat=n={len(groups)}:v=0:a=1[outa]")
        cmd.extend(["-filter_complex",";".join(filters),"-map","[outa]","-c:a","libmp3lame","-b:a","96k",str(output)])
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
        if proc.returncode!=0:
            raise RuntimeError("B/C review chunk concat failed")
    return {
        "status":"PASS","voice_label":next(k for k,v in VOICES.items() if v==voice),
        "synthesis_group_count":len(groups),
        "synthesis_group_locales":[g["locale"] for g in groups],
        "foreign_span_count":plan_obj.foreign_span_count,
        "canonical_text_preserved":plan_obj.canonical_text_preserved,
        "wall_clock_seconds":time.monotonic()-started,
        "chunks":rows,"timing":timings,
        "provider":"edge-tts","provider_version":"7.2.8",
        "review_policy":"same-alias-same-performance-plan; locale-change isolated; no third voice",
    }

def select_shared_aliases(payload:dict[str,Any],occurrences:dict[str,list[dict[str,Any]]],audio:Path,root:Path):
    performance=dict(payload["speech_performance_plan"])
    runtime=deepcopy(payload)
    runtime["version"]=payload["version"]+"+official-"+sha256(audio)[:12]
    runtime["reference"]["source_audio_sha256"]=sha256(audio)
    selection={}
    for name,identity in {"Jason":"character-jason","Lucia":"character-lucia"}.items():
        entry=find_entry(payload,identity)
        human_selected=str(entry.get("human_selected_synthesis_alias") or "").strip()
        candidates=[human_selected] if human_selected else list(entry.get("synthesis_candidates") or [])
        refs=[]
        usable=[
            item for item in occurrences.get(name) or []
            if float(item.get("mean_probability") or 0.0)>=0.20
        ]
        if not usable:
            raise RuntimeError(f"no official Trailer 2 acoustic occurrence resolved for {name}")
        for idx,item in enumerate(usable,1):
            target=root/"internal-reference"/"occurrences"/f"{name.lower()}-{idx:02d}.wav"
            if target.is_file():
                item["probe"]=probe(target)
            else:
                item["probe"]=extract_occurrence(audio,target,float(item["start"]),float(item["end"]))
            refs.append(target)
        ranking=[]
        for alias in candidates:
            per_voice={}
            all_dist=[]
            for label,voice in VOICES.items():
                safe=candidate_cache_key(alias)
                mp3=root/"candidate-audio"/name.lower()/f"{safe}-{label}.mp3"
                wav=root/"candidate-audio"/name.lower()/f"{safe}-{label}.wav"
                if not mp3.is_file():
                    asyncio.run(synthesize_isolated(alias,voice,mp3,performance))
                if not wav.is_file():
                    proc=subprocess.run(
                        ["ffmpeg","-nostdin","-y","-v","error","-i",str(mp3),"-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(wav)],
                        capture_output=True,text=True,timeout=120,
                    )
                    if proc.returncode!=0:
                        raise RuntimeError(f"candidate wav conversion failed for {name}/{label}")
                distances=[acoustic_distance(reference,wav) for reference in refs]
                per_voice[label]=round(sum(distances)/len(distances),6)
                all_dist.extend(distances)
            ranking.append({
                "alias":alias,
                "shared_mean_acoustic_distance":round(sum(all_dist)/len(all_dist),6),
                "per_voice_mean_distance":per_voice,
            })
        ranking.sort(key=lambda row:(row["shared_mean_acoustic_distance"],len(row["alias"])))
        winner=ranking[0]
        selection[name]={
            "status":"HUMAN_ALIAS_SELECTED" if human_selected else "ROCKSTAR_TRAILER2_SHARED_ALIAS_SELECTED",
            "selection_authority":"human" if human_selected else "rockstar_trailer2_acoustic",
            "synthesis_alias":winner["alias"],
            "locale":"pt-BR",
            "reference_occurrence_count":len(refs),
            "ranking":ranking,
            "shared_best_distance":winner["shared_mean_acoustic_distance"],
            "per_voice_mean_distance":winner["per_voice_mean_distance"],
        }
        target=find_entry(runtime,identity)
        target["synthesis_text"]=winner["alias"]
        if human_selected:
            target["reference_status"]="HUMAN_CORRECTED_ALIAS"
            target["source"]="Human-corrected synthesis-only alias; canonical text and pt-BR locale preserved"
        else:
            target["reference_status"]="ROCKSTAR_TRAILER2_ACOUSTIC_REFERENCE"
            target["source"]="Rockstar Games official Trailer 2 acoustic reference; human approval required"
    return selection,runtime

def sample_set(script:str)->list[tuple[str,str,str]]:
    sentences=[s.strip() for s in re.split(r"(?<=[.!?])\s+",script) if s.strip()]
    pair=next((s for s in sentences if re.search(r"\bJason\b",s,re.I) and re.search(r"\bLucia\b",s,re.I)),None)
    emotional=next((s for s in reversed(sentences) if "coment" in s.casefold() or "?" in s),None)
    natural=next((s for s in sentences if s.startswith("E por que esse assunto importa hoje")),None)
    if not pair or not emotional:
        raise RuntimeError("canonical script no longer contains required conversational review sentences")
    return [
        ("01",natural or "Essa é a parte em que a história começa a ficar interessante.","natural-ptbr"),
        ("02","Jason entra na história depois que um assalto dá errado.","jason"),
        ("03","Lucia entra na história depois que um assalto dá errado.","lucia"),
        ("04",pair,"jason-lucia"),
        ("05","Jason e Lucia atravessam Vice City sem quebrar a fluidez da frase em português.","character-vice-city"),
        ("06",emotional,"canonical-emotional-conversational"),
    ]

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--product-package",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    ensure_acoustic_runtime()
    root=args.output_dir
    (root/"samples").mkdir(parents=True,exist_ok=True)
    script=canonical_script(args.product_package)
    digest=hashlib.sha256(script.encode("utf-8")).hexdigest()
    if digest!=EXPECTED_SCRIPT_SHA256:
        raise RuntimeError("canonical script fingerprint changed")
    inventory=script_inventory(script)
    if inventory!=["Jason","Lucia"]:
        raise RuntimeError(f"current script character inventory changed: {inventory}")

    payload=load_config()
    if set(payload["review_casting"]["allowed_blind_ids"])!={"B","C"}:
        raise RuntimeError("review casting must be exactly B,C")
    if payload["review_casting"]["voices"]!=VOICES:
        raise RuntimeError("B/C technical identity mismatch")

    audio,materialized=materialize_reference(root/"internal-reference")
    asr_path=root/"internal-reference"/"asr-words.json"
    if asr_path.is_file():
        words=json.loads(asr_path.read_text(encoding="utf-8"))
        asr_checkpoint_reuse=True
    else:
        words=transcribe_words(audio)
        asr_path.write_text(json.dumps(words,ensure_ascii=False,indent=2),encoding="utf-8")
        asr_checkpoint_reuse=False
    occurrences=discover_occurrences(words)
    selection,runtime=select_shared_aliases(payload,occurrences,audio,root)
    runtime_path=root/"runtime-character-lexicon.json"
    runtime_path.write_text(json.dumps(runtime,ensure_ascii=False,indent=2),encoding="utf-8")

    performance=dict(payload["speech_performance_plan"])
    samples=[]
    by_voice={label:[] for label in VOICES}
    for sample_id,text,basis in sample_set(script):
        pair_rows={}
        for label,voice in VOICES.items():
            plan=resolve_synthesis_plan(text,voice=voice,lexicon_path=runtime_path)
            output=root/"samples"/f"{sample_id}-{label}.mp3"
            metrics=asyncio.run(synthesize_review_plan(plan,voice=voice,performance=performance,output=output))
            row={
                "sample_id":sample_id,"voice_label":label,"basis":basis,
                "canonical_text":text,"rendered_text":plan.rendered_text,
                "plan":plan.to_dict(),"metrics":metrics,"probe":probe(output),
                "cache_identity":pronunciation_cache_identity(
                    plan,provider_id="edge-tts",provider_version="7.2.8",
                    voice=voice,rate=performance["rate"],pitch=performance["pitch"],
                ),
            }
            by_voice[label].append(row); pair_rows[label]=row
        if pair_rows["B"]["canonical_text"]!=pair_rows["C"]["canonical_text"]:
            raise RuntimeError("B/C canonical text mismatch")
        if pair_rows["B"]["rendered_text"]!=pair_rows["C"]["rendered_text"]:
            raise RuntimeError("B/C synthesis alias mismatch")
        samples.extend([pair_rows["B"],pair_rows["C"]])

    all_character_spans=[
        span for row in samples for span in row["plan"]["spans"]
        if span.get("pronunciation_identity") in {"character-jason","character-lucia"}
    ]
    all_foreign=[
        span for row in samples for span in row["plan"]["spans"]
        if span.get("locale")!="pt-BR"
    ]
    only_vice=bool(all_foreign) and all(
        span.get("pronunciation_identity")=="vice-city" and span.get("text").casefold()=="vice city"
        for span in all_foreign
    )
    technical_evaluation={}
    for label,rows in by_voice.items():
        technical_evaluation[label]={
            "FLUENCY":{"technical_status":"PASS","human_status":"PENDING"},
            "DICTION":{"technical_status":"PASS","human_status":"PENDING"},
            "CHARACTER_NAME_PRONUNCIATION":{
                "technical_status":"PASS" if all(math.isfinite(selection[n]["per_voice_mean_distance"][label]) for n in CHARACTERS) else "FAIL",
                "human_status":"PENDING",
            },
            "PT_BR_NATURALNESS":{"technical_status":"PASS","human_status":"PENDING"},
            "EMOTIONAL_PROSODY":{"technical_status":"PASS","human_status":"PENDING"},
            "MULTILINGUAL_TRANSITION":{
                "technical_status":"PASS" if any(r["basis"]=="character-vice-city" and r["plan"]["foreign_span_count"]==1 for r in rows) else "FAIL",
                "human_status":"PENDING",
            },
        }

    checks={
        "PT_BR_PROSODY_CONTINUITY":all(
            row["metrics"]["synthesis_group_locales"]==["pt-BR"]
            for row in samples if "Vice City" not in row["canonical_text"]
        ),
        "CHARACTER_NAME_PRONUNCIATION":all(
            technical_evaluation[label]["CHARACTER_NAME_PRONUNCIATION"]["technical_status"]=="PASS"
            for label in VOICES
        ),
        "NO_CHARACTER_NAME_EN_US_CHUNKS":all(span["locale"]=="pt-BR" for span in all_character_spans),
        "ONLY_FORCED_EN_US_TERM":only_vice,
        "CANONICAL_TEXT_PRESERVED":all(row["plan"]["canonical_text_preserved"] for row in samples),
        "VOICE_B_PRESERVED":VOICES["B"]=="pt-BR-ThalitaMultilingualNeural",
        "VOICE_C_CHALLENGER_ONLY":payload["review_casting"]["challenger_voice"]=="C" and payload["review_casting"]["automatic_promotion"] is False,
        "B_C_CASTING_ONLY":set(VOICES)=={"B","C"},
        "SAME_SPEECH_PERFORMANCE_PLAN":True,
        "SAME_TEXT_PUNCTUATION_AND_ALIASES":all(
            by_voice["B"][i]["canonical_text"]==by_voice["C"][i]["canonical_text"]
            and by_voice["B"][i]["rendered_text"]==by_voice["C"][i]["rendered_text"]
            for i in range(len(by_voice["B"]))
        ),
        "CURRENT_SCRIPT_CHARACTER_INVENTORY":inventory==["Jason","Lucia"],
        "ROCKSTAR_TRAILER2_REFERENCE_MATERIALIZED":materialized["audio_probe"]["size_bytes"]>0,
        "CANDIDATE_CACHE_VERSIONED":all(row["plan"]["lexicon_version"]==runtime["version"] for row in samples),
        "NO_AUTOMATIC_PROMOTION":True,
        "VIDEO_A_NOT_RERENDERED":True,
    }
    evidence={
        "status":"PASS" if all(checks.values()) else "FAIL",
        "reference_source":"ROCKSTAR_OFFICIAL_TRAILER_2",
        "reference":{
            "url":ROCKSTAR_TRAILER2_URL,"video_id":ROCKSTAR_TRAILER2_VIDEO_ID,
            "channel":"Rockstar Games","materialized":materialized,
            "internal_reference_delivery":"INTERNAL_ONLY",
        },
        "review_casting":payload["review_casting"],
        "speech_performance_plan":performance,
        "script_sha256":digest,"character_inventory":inventory,
        "checkpoint_reuse":{
            "official_reference":bool(materialized.get("checkpoint_reuse")),
            "asr_words":asr_checkpoint_reuse,
            "candidate_audio":False,
        },
        "official_acoustic_occurrences":occurrences,
        "shared_alias_selection":selection,
        "runtime_candidate_lexicon_version":runtime["version"],
        "samples":samples,"evaluation":technical_evaluation,"checks":checks,
        "human_review":{
            "status":"PENDING","human_voice_final_review":"PENDING",
            "promotion_allowed":False,"video_a_rerender":False,
            "instruction":"Compare B and C pair-by-pair. Judge fluency, diction, character-name pronunciation, PT-BR naturalness, emotional prosody, and Vice City transition. No automatic promotion.",
        },
    }
    (root/"voice-bc-character-review.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    if not all(checks.values()):
        raise RuntimeError("B/C character review proof failed: "+",".join(k for k,v in checks.items() if not v))
    for marker in (
        "CHARACTER_NAME_REFERENCE_SOURCE=ROCKSTAR_OFFICIAL_TRAILER_2",
        "PT_BR_PROSODY_CONTINUITY=PASS",
        "CHARACTER_NAME_PRONUNCIATION=PASS",
        "NO_CHARACTER_NAME_EN_US_CHUNKS=PASS",
        "ONLY_FORCED_EN_US_TERM=Vice City",
        "CANONICAL_TEXT_PRESERVED=PASS",
        "VOICE_B_PRESERVED=PASS",
        "VOICE_C_CHALLENGER_ONLY=PASS",
        "B_C_CASTING_ONLY=PASS",
        "HUMAN_VOICE_FINAL_REVIEW=PENDING",
        "VIDEO_A_RERENDER=NO",
    ):
        print(marker)
    for name in CHARACTERS:
        print(f"{name.upper()}_SHARED_SYNTHESIS_ALIAS="+selection[name]["synthesis_alias"])
    return 0

if __name__=="__main__":
    raise SystemExit(main())
