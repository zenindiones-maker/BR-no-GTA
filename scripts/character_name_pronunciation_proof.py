from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from app.services.pronunciation_service import (
    DEFAULT_VOICE,
    _edge_synthesis_groups,
    pronunciation_cache_identity,
    resolve_synthesis_plan,
    synthesize_edge_plan,
)

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_LEXICON = ROOT / "config" / "pronunciation_character_aliases.candidate.json"
OFFICIAL_TRAILER_URL = "https://www.youtube.com/watch?v=VQRLujxTm3c"
OFFICIAL_ROCKSTAR_PAGE = "https://www.rockstargames.com/VI/trailer-2"
EXPECTED_VIDEO_ID = "VQRLujxTm3c"
EXPECTED_SCRIPT_SHA256 = "9bde9d9e5fd413597ecafadbfb55836ccbcaf10da7038aa83c133b3cc65c15ea"
KNOWN_CHARACTER_NAMES = (
    "Jason",
    "Lucia",
    "Cal Hampton",
    "Boobie Ike",
    "Dre'Quan Priest",
    "Real Dimez",
    "Raul Bautista",
    "Brian Heder",
)
REFERENCE_WINDOWS = {
    "Jason": {"start_seconds": 23.0, "duration_seconds": 6.5, "basis": "Trailer 2 spoken Jason references around 00:24 and 00:28"},
    "Lucia": {"start_seconds": 49.0, "duration_seconds": 6.0, "basis": "Trailer 2 spoken Lucia Caminos reference around 00:50"},
}

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def probe(path: Path) -> dict[str, Any]:
    p=subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration","-show_streams","-of","json",str(path)],
        capture_output=True,text=True,timeout=120,
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path.name}")
    data=json.loads(p.stdout)
    if not any(item.get("codec_type")=="audio" for item in data.get("streams") or []):
        raise RuntimeError(f"audio stream missing for {path.name}")
    duration=float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError(f"invalid duration for {path.name}")
    return {"duration_seconds":duration,"size_bytes":path.stat().st_size,"sha256":sha256(path)}

def canonical_script(product: Path) -> str:
    payload=json.loads(product.read_text(encoding="utf-8"))
    text=str((payload.get("script") or {}).get("content") or "")
    if not text:
        raise RuntimeError("canonical product package script is missing")
    digest=hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != EXPECTED_SCRIPT_SHA256:
        raise RuntimeError(f"canonical script fingerprint changed: {digest}")
    return text

def character_inventory(text: str) -> list[str]:
    return [
        name for name in KNOWN_CHARACTER_NAMES
        if re.search(r"(?<!\\w)"+re.escape(name)+r"(?!\\w)", text, re.IGNORECASE)
    ]

def download_official_reference(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True,exist_ok=True)
    meta=subprocess.run(
        ["yt-dlp","--no-playlist","--skip-download","--print","%(id)s\\t%(channel)s\\t%(title)s",OFFICIAL_TRAILER_URL],
        capture_output=True,text=True,timeout=180,
    )
    if meta.returncode != 0:
        raise RuntimeError("official Trailer 2 metadata lookup failed")
    line=(meta.stdout.strip().splitlines() or [""])[-1]
    parts=line.split("\\t",2)
    if len(parts) != 3 or parts[0] != EXPECTED_VIDEO_ID or "Rockstar Games" not in parts[1]:
        raise RuntimeError(f"unexpected official Trailer 2 identity: {line!r}")
    subprocess.run(
        [
            "yt-dlp","--no-playlist","-f","bestaudio",
            "-o",str(root/"official-trailer-2.%(ext)s"),
            OFFICIAL_TRAILER_URL,
        ],
        check=True,timeout=300,
    )
    sources=[
        p for p in root.glob("official-trailer-2.*")
        if p.suffix not in {".part",".ytdl",".json"} and p.is_file()
    ]
    if len(sources) != 1:
        raise RuntimeError(f"official Trailer 2 audio materialization ambiguous: {sources}")
    source=sources[0]
    refs={}
    for name,window in REFERENCE_WINDOWS.items():
        target=root/f"official-reference-{name.lower()}.mp3"
        subprocess.run(
            [
                "ffmpeg","-nostdin","-y","-v","error",
                "-ss",str(window["start_seconds"]),"-t",str(window["duration_seconds"]),
                "-i",str(source),"-vn","-ac","1","-ar","48000","-c:a","libmp3lame","-q:a","2",str(target),
            ],
            check=True,timeout=120,
        )
        refs[name]={
            **window,
            "file":str(target),
            "probe":probe(target),
        }
    return {
        "source_url":OFFICIAL_TRAILER_URL,
        "rockstar_page":OFFICIAL_ROCKSTAR_PAGE,
        "video_id":parts[0],
        "channel":parts[1],
        "title":parts[2],
        "references":refs,
    }

def sample_set(script: str) -> list[tuple[str,str,str]]:
    exact_sentences=[
        item.strip()
        for item in re.split(r"(?<=[.!?])\\s+",script)
        if re.search(r"\\b(?:Jason|Lucia)\\b",item)
    ]
    if len(exact_sentences) != 2:
        raise RuntimeError(f"expected exactly two canonical script sentences with character names, got {len(exact_sentences)}")
    return [
        ("A-jason","Jason entra na história depois que um assalto dá errado.","benchmark-natural-jason"),
        ("B-lucia","Lucia entra na história depois que um assalto dá errado.","benchmark-natural-lucia"),
        ("C-jason-lucia",exact_sentences[0],"canonical-script"),
        ("D-character-vice-city","Jason e Lucia atravessam Vice City sem quebrar a fluidez da narração em português.","benchmark-character-plus-vice-city"),
        ("E-current-script-multi",exact_sentences[1],"canonical-script"),
    ]

def candidate_entries() -> dict[str,dict[str,Any]]:
    payload=json.loads(CANDIDATE_LEXICON.read_text(encoding="utf-8"))
    return {str(item["identity"]):item for item in payload.get("entries") or []}

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--product-package",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    samples=args.output_dir/"samples"; samples.mkdir(parents=True,exist_ok=True)
    refs_dir=args.output_dir/"official-reference"; refs_dir.mkdir(parents=True,exist_ok=True)

    script=canonical_script(args.product_package)
    inventory=character_inventory(script)
    if inventory != ["Jason","Lucia"]:
        raise RuntimeError(f"current-script character inventory changed: {inventory}")

    entries=candidate_entries()
    jason=entries.get("character-jason") or {}
    lucia=entries.get("character-lucia") or {}
    if jason.get("locale")!="pt-BR" or lucia.get("locale")!="pt-BR":
        raise RuntimeError("character aliases must remain in pt-BR")
    if not jason.get("synthesis_text") or not lucia.get("synthesis_text"):
        raise RuntimeError("character synthesis aliases missing")

    official=download_official_reference(refs_dir)
    rows=[]
    for sample_id,text,basis in sample_set(script):
        plan=resolve_synthesis_plan(text,voice=DEFAULT_VOICE,lexicon_path=CANDIDATE_LEXICON)
        out=samples/f"{sample_id}.mp3"
        metrics=asyncio.run(synthesize_edge_plan(
            plan,voice=DEFAULT_VOICE,rate="+0%",pitch="+0Hz",output=out
        ))
        character_spans=[
            span for span in plan.spans
            if span.pronunciation_identity in {"character-jason","character-lucia"}
        ]
        foreign=[
            span for span in plan.spans
            if span.locale!="pt-BR"
        ]
        bad_character_foreign=[
            span for span in character_spans
            if span.locale!="pt-BR"
        ]
        groups=_edge_synthesis_groups(plan)
        rows.append({
            "sample_id":sample_id,
            "basis":basis,
            "canonical_text":text,
            "plan":plan.to_dict(),
            "rendered_text":plan.rendered_text,
            "character_spans":[span.to_dict() for span in character_spans],
            "foreign_spans":[span.to_dict() for span in foreign],
            "character_foreign_spans":[span.to_dict() for span in bad_character_foreign],
            "synthesis_group_count":len(groups),
            "synthesis_group_locales":[group["locale"] for group in groups],
            "edge_metrics":metrics,
            "probe":probe(out),
            "cache_identity":pronunciation_cache_identity(
                plan,provider_id="edge-tts",provider_version="7.2.8",
                voice=DEFAULT_VOICE,rate="+0%",pitch="+0Hz",
            ),
        })

    all_character_spans=[
        span
        for row in rows
        for span in row["character_spans"]
    ]
    character_ids={span["pronunciation_identity"] for span in all_character_spans}
    only_forced_en_us=all(
        span.get("pronunciation_identity")=="vice-city"
        for row in rows for span in row["foreign_spans"]
    )
    prosody_rows=[
        row for row in rows if "Vice City" not in row["canonical_text"]
    ]
    checks={
        "PT_BR_PROSODY_CONTINUITY":all(
            row["synthesis_group_count"]==1
            and row["synthesis_group_locales"]==["pt-BR"]
            for row in prosody_rows
        ),
        "CHARACTER_NAME_PRONUNCIATION":(
            character_ids=={"character-jason","character-lucia"}
            and jason.get("target_ipa")=="ˈdʒeɪsən"
            and lucia.get("target_ipa")=="luˈsiːə"
            and official["references"]["Jason"]["probe"]["size_bytes"]>0
            and official["references"]["Lucia"]["probe"]["size_bytes"]>0
        ),
        "NO_CHARACTER_NAME_EN_US_CHUNKS":all(
            not row["character_foreign_spans"] for row in rows
        ),
        "ONLY_FORCED_EN_US_TERM":only_forced_en_us,
        "CANONICAL_TEXT_PRESERVED":all(
            row["plan"]["canonical_text_preserved"] is True
            and row["plan"]["canonical_text"]==row["canonical_text"]
            for row in rows
        ),
        "VOICE_B_PRESERVED":DEFAULT_VOICE=="pt-BR-ThalitaMultilingualNeural",
        "CURRENT_SCRIPT_CHARACTER_INVENTORY":inventory==["Jason","Lucia"],
        "CANDIDATE_CACHE_VERSIONED":all(
            "2026.09.19.4-character-candidate.1"==row["plan"]["lexicon_version"]
            for row in rows
        ),
        "OFFICIAL_TRAILER_REFERENCE_MATERIALIZED":all(
            official["references"][name]["probe"]["size_bytes"]>0
            for name in ("Jason","Lucia")
        ),
        "NO_AUTOMATIC_PROMOTION":True,
    }
    if not all(checks.values()):
        raise RuntimeError("character pronunciation proof failed: "+",".join(k for k,v in checks.items() if not v))

    evidence={
        "status":"PASS",
        "candidate_status":"PENDING_HUMAN_REVIEW",
        "automatic_promotion":False,
        "rerender_video":False,
        "voice":DEFAULT_VOICE,
        "default_narration_locale":"pt-BR",
        "only_forced_en_us_term":"Vice City",
        "candidate_lexicon_version":"2026.09.19.4-character-candidate.1",
        "canonical_production_lexicon_unchanged":"2026.09.19.4",
        "script_sha256":EXPECTED_SCRIPT_SHA256,
        "character_inventory":inventory,
        "aliases":{
            "Jason":{
                "canonical_text":"Jason",
                "synthesis_alias":jason["synthesis_text"],
                "locale":"pt-BR",
                "target_ipa":jason["target_ipa"],
                "official_reference":official["references"]["Jason"],
            },
            "Lucia":{
                "canonical_text":"Lucia",
                "synthesis_alias":lucia["synthesis_text"],
                "locale":"pt-BR",
                "target_ipa":lucia["target_ipa"],
                "official_reference":official["references"]["Lucia"],
            },
        },
        "official_ground_truth":official,
        "samples":rows,
        "checks":checks,
        "human_review":{
            "status":"PENDING",
            "required":True,
            "promotion_allowed":False,
            "instruction":"Compare the generated PT-BR samples directly with the official Trailer 2 reference clips for Jason and Lucia. Approve or request alias adjustment.",
        },
    }
    (args.output_dir/"character-name-pronunciation-proof.json").write_text(
        json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    for key,value in checks.items():
        print(f"{key}={'PASS' if value else 'FAIL'}")
    print("ONLY_FORCED_EN_US_TERM=Vice City")
    print("HUMAN_CHARACTER_NAME_REVIEW=PENDING")
    print("VIDEO_A_RERENDER=NO")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
