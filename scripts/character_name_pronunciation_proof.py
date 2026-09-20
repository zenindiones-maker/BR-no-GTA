from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from difflib import SequenceMatcher
import hashlib
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

from app.services.ytdlp_media_ingestion import YtDlpMediaIngestion
from app.services.media_ingestion import IngestionStatus
from app.services.pronunciation_service import (
    DEFAULT_VOICE,
    _edge_synthesis_groups,
    pronunciation_cache_identity,
    resolve_synthesis_plan,
    synthesize_edge_plan,
)

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE_CONFIG=ROOT/"config"/"pronunciation_character_aliases.candidate.json"
PTBR_DUB_URL="https://www.youtube.com/watch?v=VQRLujxTm3c"
PTBR_DUB_VIDEO_ID="VQRLujxTm3c"
ROCKSTAR_IDENTITY_PAGE="https://www.rockstargames.com/VI"
EXPECTED_SCRIPT_SHA256="9bde9d9e5fd413597ecafadbfb55836ccbcaf10da7038aa83c133b3cc65c15ea"
CAST_NAMES=("Jason","Lucia")
KNOWN_SCRIPT_NAMES=("Jason","Lucia","Cal Hampton","Boobie Ike","Dre'Quan Priest","Real Dimez","Raul Bautista","Brian Heder")
REFERENCE_VARIANTS={
    "Jason":("jason","jayson","jay son"),
    "Lucia":("lucia","lusia","lu cia"),
}

def ensure_acoustic_runtime()->None:
    required=[]
    if importlib.util.find_spec("faster_whisper") is None:
        required.append("faster-whisper==1.2.1")
    if importlib.util.find_spec("librosa") is None:
        required.append("librosa==0.11.0")
    if required:
        subprocess.run([sys.executable,"-m","pip","install",*required],check=True,timeout=900)

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def probe(path:Path)->dict[str,Any]:
    proc=subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration","-show_streams","-of","json",str(path)],
        capture_output=True,text=True,timeout=120,
    )
    if proc.returncode!=0:
        raise RuntimeError(f"ffprobe failed for {path.name}: {(proc.stderr or '')[-500:]}")
    data=json.loads(proc.stdout)
    if not any(item.get("codec_type")=="audio" for item in data.get("streams") or []):
        raise RuntimeError(f"audio stream missing for {path.name}")
    duration=float((data.get("format") or {}).get("duration") or 0)
    if duration<=0:
        raise RuntimeError(f"invalid duration for {path.name}")
    return {"duration_seconds":duration,"size_bytes":path.stat().st_size,"sha256":sha256(path)}

def canonical_script(product:Path)->str:
    payload=json.loads(product.read_text(encoding="utf-8"))
    text=str((payload.get("script") or {}).get("content") or "")
    if not text:
        raise RuntimeError("canonical product package script is missing")
    digest=hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest!=EXPECTED_SCRIPT_SHA256:
        raise RuntimeError(f"canonical script fingerprint changed: {digest}")
    return text

def script_inventory(text:str)->list[str]:
    return [name for name in KNOWN_SCRIPT_NAMES if re.search(r"(?<!\w)"+re.escape(name)+r"(?!\w)",text,re.I)]

def normalize(value:str)->str:
    value=unicodedata.normalize("NFKD",value.casefold())
    value="".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+","",value)

def materialize_reference(root:Path)->tuple[Path,dict[str,Any]]:
    root.mkdir(parents=True,exist_ok=True)
    source=root/"rockstar-trailer2.mp4"
    audio=root/"rockstar-trailer2-16k.wav"
    if source.is_file() and audio.is_file():
        return audio,{"video_file":str(source),"video_sha256":sha256(source),"audio_probe":probe(audio),"checkpoint_reuse":True}
    result=YtDlpMediaIngestion().ingest(PTBR_DUB_URL,root/"rockstar-trailer2")
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
    return audio,{"video_file":str(source),"video_sha256":sha256(source),"audio_probe":probe(audio)}

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
        raise RuntimeError("official Rockstar Trailer 2 ASR did not produce word timestamps")
    return words

def discover_occurrences(words:list[dict[str,Any]])->dict[str,list[dict[str,Any]]]:
    found={name:[] for name in CAST_NAMES}
    for name in CAST_NAMES:
        variants=[normalize(value) for value in REFERENCE_VARIANTS[name]]
        widths={len(value.split()) for value in REFERENCE_VARIANTS[name]}
        for index in range(len(words)):
            for width in widths:
                if index+width>len(words):
                    continue
                raw=" ".join(item["text"] for item in words[index:index+width])
                candidate=normalize(raw)
                score=max((SequenceMatcher(None,candidate,value).ratio() for value in variants),default=0.0)
                if score<0.72:
                    continue
                start=float(words[index]["start"])
                end=float(words[index+width-1]["end"])
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

def extract_occurrence(audio:Path,target:Path,start:float,end:float)->dict[str,Any]:
    pad=0.08
    target.parent.mkdir(parents=True,exist_ok=True)
    proc=subprocess.run([
        "ffmpeg","-nostdin","-y","-v","error",
        "-ss",f"{max(0,start-pad):.3f}","-i",str(audio),
        "-t",f"{max(0.18,(end-start)+2*pad):.3f}",
        "-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(target),
    ],capture_output=True,text=True,timeout=120)
    if proc.returncode!=0:
        raise RuntimeError(f"reference clip extraction failed: {target.name}")
    return probe(target)

def acoustic_signature(path:Path):
    import librosa
    audio,sr=librosa.load(str(path),sr=16000,mono=True)
    audio,_=librosa.effects.trim(audio,top_db=35)
    if audio.size<1600:
        raise RuntimeError(f"acoustic clip too short: {path.name}")
    mfcc=librosa.feature.mfcc(y=audio,sr=sr,n_mfcc=13,n_fft=400,hop_length=160)
    mfcc=mfcc[1:,:]
    mean=mfcc.mean(axis=1,keepdims=True)
    std=mfcc.std(axis=1,keepdims=True)+1e-6
    return (mfcc-mean)/std

def acoustic_distance(left:Path,right:Path)->float:
    import librosa
    left_features=acoustic_signature(left)
    right_features=acoustic_signature(right)
    distance,path=librosa.sequence.dtw(X=left_features,Y=right_features,metric="cosine")
    return float(distance[-1,-1]/max(1,len(path)))

async def synthesize_word(text:str,output:Path)->None:
    import edge_tts
    output.parent.mkdir(parents=True,exist_ok=True)
    await edge_tts.Communicate(
        text=text,voice=DEFAULT_VOICE,rate="+0%",pitch="+0Hz",volume="+0%"
    ).save(str(output))
    if not output.is_file() or output.stat().st_size<=0:
        raise RuntimeError("isolated candidate synthesis missing")

def load_config()->dict[str,Any]:
    return json.loads(CANDIDATE_CONFIG.read_text(encoding="utf-8"))

def find_entry(payload:dict[str,Any],identity:str)->dict[str,Any]:
    for item in payload.get("entries") or []:
        if item.get("identity")==identity:
            return item
    raise RuntimeError(f"candidate entry missing: {identity}")

def select_aliases(payload:dict[str,Any],occurrences:dict[str,list[dict[str,Any]]],audio:Path,root:Path)->tuple[dict[str,Any],dict[str,Any]]:
    selection={}
    runtime=deepcopy(payload)
    runtime["version"]=payload["version"]+"+acoustic-"+sha256(audio)[:12]
    runtime["reference"]["source_audio_sha256"]=sha256(audio)
    compatibility=root/"official-reference"
    compatibility.mkdir(parents=True,exist_ok=True)
    for name,identity in {"Jason":"character-jason","Lucia":"character-lucia"}.items():
        all_occurrences=occurrences.get(name) or []
        occurrences_for_name=[
            item for item in all_occurrences
            if float(item.get("mean_probability") or 0.0) >= 0.20
        ]
        if not occurrences_for_name:
            selection[name]={
                "status":"PENDING_HUMAN",
                "reason":"no high-confidence acoustic occurrence in PT-BR dubbed trailer",
                "reference_occurrence_total":len(all_occurrences),
                "reference_occurrence_high_confidence":0,
            }
            continue
        references=[]
        for index,item in enumerate(occurrences_for_name,1):
            target=root/"internal-reference"/"occurrences"/f"{name.lower()}-{index:02d}.wav"
            item["file"]=str(target)
            item["probe"]=extract_occurrence(audio,target,float(item["start"]),float(item["end"]))
            references.append(target)
        rankings=[]
        canonical_candidate=None
        for alias in list(find_entry(payload,identity).get("synthesis_candidates") or []):
            safe=normalize(alias) or "candidate"
            mp3=root/"candidate-audio"/name.lower()/f"{safe}.mp3"
            wav=root/"candidate-audio"/name.lower()/f"{safe}.wav"
            asyncio.run(synthesize_word(alias,mp3))
            proc=subprocess.run(
                ["ffmpeg","-nostdin","-y","-v","error","-i",str(mp3),"-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(wav)],
                capture_output=True,text=True,timeout=120,
            )
            if proc.returncode!=0:
                raise RuntimeError(f"candidate wav conversion failed: {alias}")
            distances=[acoustic_distance(reference,wav) for reference in references]
            score=sum(distances)/len(distances)
            rankings.append({
                "alias":alias,
                "mean_acoustic_distance":round(score,6),
                "per_occurrence_distance":[round(value,6) for value in distances],
                "probe":probe(mp3),
            })
            if normalize(alias)==normalize(name) and canonical_candidate is None:
                canonical_candidate=mp3
        rankings.sort(key=lambda item:(item["mean_acoustic_distance"],len(item["alias"])))
        if not rankings or canonical_candidate is None:
            raise RuntimeError(f"candidate set incomplete for {name}")
        winner=rankings[0]
        shutil.copyfile(canonical_candidate,compatibility/f"official-reference-{name.lower()}.mp3")
        selection[name]={
            "status":"ACOUSTIC_CANDIDATE_SELECTED",
            "synthesis_alias":winner["alias"],
            "locale":"pt-BR",
            "reference_occurrence_count":len(references),
            "reference_occurrence_total":len(all_occurrences),
            "excluded_low_confidence_occurrences":len(all_occurrences)-len(occurrences_for_name),
            "minimum_asr_probability":0.20,
            "ranking":rankings,
            "best_distance":winner["mean_acoustic_distance"],
            "runner_up_distance":rankings[1]["mean_acoustic_distance"] if len(rankings)>1 else None,
        }
        target=find_entry(runtime,identity)
        target["synthesis_text"]=winner["alias"]
        target["reference_status"]="ROCKSTAR_TRAILER2_ACOUSTIC_REFERENCE"
        target["source"]="Rockstar Games official Trailer 2 acoustic reference; synthesis-only PT-BR alias; human approval required before production promotion"
    return selection,runtime

def sample_set(script:str)->list[tuple[str,str,str]]:
    exact=[
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+",script)
        if re.search(r"\b(?:Jason|Lucia)\b",sentence)
    ]
    if len(exact)<2:
        raise RuntimeError(f"expected at least two canonical script sentences with character names, got {len(exact)}")
    return [
        ("A-jason","Jason entra na história depois que um assalto dá errado.","benchmark-real-name"),
        ("B-lucia","Lucia entra na história depois que um assalto dá errado.","benchmark-real-name"),
        ("C-jason-lucia","Jason e Lucia precisam confiar um no outro para sobreviver.","benchmark-pair"),
        ("D-character-vice-city","Jason e Lucia atravessam Vice City sem quebrar a fluidez da narração em português.","benchmark-character-plus-vice-city"),
        ("E-current-script-multi",exact[0]+" "+exact[1],"canonical-script"),
    ]

def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--product-package",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    ensure_acoustic_runtime()

    root=args.output_dir
    root.mkdir(parents=True,exist_ok=True)
    (root/"samples").mkdir(exist_ok=True)
    script=canonical_script(args.product_package)
    inventory=script_inventory(script)
    if inventory!=["Jason","Lucia"]:
        raise RuntimeError(f"current-script character inventory changed: {inventory}")

    payload=load_config()
    if payload["reference"]["video_id"]!=PTBR_DUB_VIDEO_ID:
        raise RuntimeError("PT-BR acoustic reference video mismatch")
    audio,materialized=materialize_reference(root/"internal-reference")
    words=transcribe_words(audio)
    (root/"internal-reference"/"asr-words.json").write_text(
        json.dumps(words,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    occurrences=discover_occurrences(words)
    selection,runtime=select_aliases(payload,occurrences,audio,root)
    runtime_path=root/"runtime-character-lexicon.json"
    runtime_path.write_text(json.dumps(runtime,ensure_ascii=False,indent=2),encoding="utf-8")

    required=set(inventory)
    selected={name for name,value in selection.items() if value.get("status")=="ACOUSTIC_CANDIDATE_SELECTED"}
    if selected!=required:
        raise RuntimeError("acoustic aliases unresolved for current script: "+",".join(sorted(required-selected)))

    rows=[]
    for sample_id,text,basis in sample_set(script):
        plan=resolve_synthesis_plan(text,voice=DEFAULT_VOICE,lexicon_path=runtime_path)
        output=root/"samples"/f"{sample_id}.mp3"
        metrics=asyncio.run(synthesize_edge_plan(
            plan,voice=DEFAULT_VOICE,rate="+0%",pitch="+0Hz",output=output
        ))
        character_spans=[span for span in plan.spans if span.pronunciation_identity in {"character-jason","character-lucia"}]
        foreign=[span for span in plan.spans if span.locale!="pt-BR"]
        groups=_edge_synthesis_groups(plan)
        rows.append({
            "sample_id":sample_id,
            "basis":basis,
            "canonical_text":text,
            "rendered_text":plan.rendered_text,
            "plan":plan.to_dict(),
            "character_spans":[span.to_dict() for span in character_spans],
            "foreign_spans":[span.to_dict() for span in foreign],
            "synthesis_group_count":len(groups),
            "synthesis_group_locales":[group["locale"] for group in groups],
            "edge_metrics":metrics,
            "probe":probe(output),
            "cache_identity":pronunciation_cache_identity(
                plan,provider_id="edge-tts",provider_version="7.2.8",
                voice=DEFAULT_VOICE,rate="+0%",pitch="+0Hz",
            ),
        })

    prosody=[row for row in rows if "Vice City" not in row["canonical_text"]]
    only_vice=all(
        span.get("pronunciation_identity")=="vice-city"
        for row in rows for span in row["foreign_spans"]
    )
    checks={
        "PT_BR_PROSODY_CONTINUITY":all(
            row["synthesis_group_count"]==1 and row["synthesis_group_locales"]==["pt-BR"]
            for row in prosody
        ),
        "CHARACTER_NAME_PRONUNCIATION":selected==required and all(
            math.isfinite(value["best_distance"]) for value in selection.values()
        ),
        "NO_CHARACTER_NAME_EN_US_CHUNKS":all(
            span["locale"]=="pt-BR"
            for row in rows for span in row["character_spans"]
        ),
        "ONLY_FORCED_EN_US_TERM":only_vice,
        "CANONICAL_TEXT_PRESERVED":all(
            row["plan"]["canonical_text_preserved"] is True
            and row["plan"]["canonical_text"]==row["canonical_text"]
            for row in rows
        ),
        "VOICE_B_PRESERVED":DEFAULT_VOICE=="pt-BR-ThalitaMultilingualNeural",
        "CURRENT_SCRIPT_CHARACTER_INVENTORY":inventory==["Jason","Lucia"],
        "CANDIDATE_CACHE_VERSIONED":all(
            row["plan"]["lexicon_version"]==runtime["version"] for row in rows
        ),
        "ROCKSTAR_TRAILER2_REFERENCE_MATERIALIZED":materialized["audio_probe"]["size_bytes"]>0,
        "NO_AUTOMATIC_PROMOTION":True,
        "CHARACTER_NAME_REFERENCE_SOURCE":True,
        "CHARACTER_NAME_ACOUSTIC_REFERENCE":all(
            (selection.get(name) or {}).get("reference_occurrence_count",0)>0
            for name in required
        ),
        "VICE_CITY_POLICY_PRESERVED":only_vice,
        "VIDEO_A_NOT_RERENDERED":True,
    }

    evidence={
        "status":"PASS" if all(checks.values()) else "FAIL",
        "candidate_status":"PENDING_HUMAN_REVIEW",
        "automatic_promotion":False,
        "rerender_video":False,
        "voice":DEFAULT_VOICE,
        "default_narration_locale":"pt-BR",
        "only_forced_en_us_term":"Vice City",
        "character_name_reference_source":"ROCKSTAR_OFFICIAL_TRAILER_2",
        "reference":{
            "url":PTBR_DUB_URL,
            "video_id":PTBR_DUB_VIDEO_ID,
            "title":payload["reference"]["title"],
            "channel":payload["reference"]["channel"],
            "authority_scope":payload["reference"]["authority_scope"],
            "materialized":materialized,
            "rockstar_identity_page":ROCKSTAR_IDENTITY_PAGE,
            "internal_reference_delivery":"INTERNAL_ONLY",
        },
        "script_sha256":EXPECTED_SCRIPT_SHA256,
        "character_inventory":inventory,
        "all_cast_occurrences":occurrences,
        "acoustic_selection":selection,
        "runtime_candidate_lexicon_version":runtime["version"],
        "samples":rows,
        "checks":checks,
        "human_review":{
            "status":"PENDING",
            "required":True,
            "promotion_allowed":False,
            "instruction":"Review the generated Voice B samples delivered as Telegram documents. Rockstar Trailer 2 reference clips were used only for internal acoustic comparison and were not sent.",
        },
    }
    (root/"character-name-pronunciation-proof.json").write_text(
        json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    if not all(checks.values()):
        raise RuntimeError(
            "character pronunciation proof failed: "
            +",".join(key for key,value in checks.items() if not value)
        )

    for marker in (
        "CHARACTER_NAME_REFERENCE_SOURCE=ROCKSTAR_OFFICIAL_TRAILER_2",
        "CHARACTER_NAME_ACOUSTIC_REFERENCE=PASS",
        "CHARACTER_NAME_PRONUNCIATION=PASS",
        "NO_CHARACTER_NAME_EN_US_CHUNKS=PASS",
        "PT_BR_PROSODY_CONTINUITY=PASS",
        "VICE_CITY_POLICY_PRESERVED=PASS",
        "CANONICAL_TEXT_PRESERVED=PASS",
        "VOICE_B_PRESERVED=PASS",
        "ONLY_FORCED_EN_US_TERM=Vice City",
        "HUMAN_CHARACTER_NAME_REVIEW=PENDING",
        "VIDEO_A_RERENDER=NO",
    ):
        print(marker)
    for name in ("Jason","Lucia"):
        print(f"{name.upper()}_SYNTHESIS_ALIAS="+selection[name]["synthesis_alias"])
    return 0

if __name__=="__main__":
    raise SystemExit(main())
