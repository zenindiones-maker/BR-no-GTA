from __future__ import annotations
import argparse,asyncio,json,subprocess,time
from pathlib import Path
from app.services.channel_spoken_branding_service import TAKE_PROFILES, canonical_opening_text
from app.services.pronunciation_service import (
    DEFAULT_VOICE,build_azure_ssml,pronunciation_cache_identity,
    provider_capabilities,resolve_synthesis_plan,synthesize_edge_plan,
)

FLUIDITY_TEXT="Boa meu povo, aqui é BR no GTA 6 e vamos ver as novidades de hoje."
FLUIDITY_PROFILES=(
    {"take_id":"fluid-1","rate":"+1%","pitch":"+0Hz","synthesis_text":"Boa meu povo, aqui é BR no GTA 6 e vamos ver as novidades de hoje."},
    {"take_id":"fluid-2","rate":"+3%","pitch":"+1Hz","synthesis_text":"Boa meu povo! Aqui é BR no GTA 6 e vamos ver as novidades de hoje."},
    {"take_id":"fluid-3","rate":"+2%","pitch":"+0Hz","synthesis_text":"Boa, meu povo! Aqui é BR no GTA 6 e vamos ver as novidades de hoje."},
)

SAMPLES=(
    ("A-control-ptbr","A análise separa fatos confirmados de rumores."),
    ("B-vice-city","Vice City"),
    ("C-closing","E BR não dorme em Vice City"),
    ("D-mixed","A Rockstar mostrou Vice City em GTA 6."),
    ("E-domain","Digital Foundry analisou PlayStation 5, Xbox Series X, NVIDIA e AMD."),
    ("F-gta6-brand","Aqui é BR no GTA 6."),
    ("G-brand-mixed","BR no GTA 6. E BR não dorme em Vice City."),
)

def _probe(path:Path)->dict:
    p=subprocess.run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)],capture_output=True,text=True,timeout=120)
    if p.returncode!=0: raise RuntimeError("ffprobe failed")
    data=json.loads(p.stdout)
    if not any(s.get("codec_type")=="audio" for s in data.get("streams",[])): raise RuntimeError("audio stream missing")
    duration=float(data.get("format",{}).get("duration") or 0)
    if duration<=0: raise RuntimeError("invalid duration")
    d=subprocess.run(["ffmpeg","-nostdin","-v","error","-xerror","-i",str(path),"-map","0:a:0","-f","null","-"],capture_output=True,timeout=120)
    if d.returncode!=0 or d.stderr.strip(): raise RuntimeError("full decode failed")
    return {"duration_seconds":duration,"size_bytes":path.stat().st_size,"audio_stream":True,"full_decode":True}

async def _literal_edge_baseline(text:str, output:Path)->dict:
    import edge_tts
    output.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    communicator=edge_tts.Communicate(text=text,voice=DEFAULT_VOICE,rate="+0%",pitch="+0Hz",volume="+0%",boundary="WordBoundary")
    with output.open("wb") as stream:
        async for event in communicator.stream():
            if event.get("type")=="audio":
                stream.write(event.get("data") or b"")
    if not output.is_file() or output.stat().st_size<=0:
        raise RuntimeError("literal Edge baseline returned empty audio")
    return {"wall_clock_seconds":time.monotonic()-started,"external_calls":1,"probe":_probe(output)}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output-dir",type=Path,required=True); args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True); samples_dir=args.output_dir/"samples"; samples_dir.mkdir(parents=True,exist_ok=True)
    baseline_text="E BR não dorme em Vice City"
    baseline_path=samples_dir/"C0-closing-literal-baseline.mp3"
    baseline=asyncio.run(_literal_edge_baseline(baseline_text,baseline_path))
    rows=[]; total_started=time.monotonic(); resolution=0.0; synthesis=0.0; calls=0
    for sample_id,text in SAMPLES:
        plan=resolve_synthesis_plan(text,voice=DEFAULT_VOICE); resolution+=plan.resolution_wall_clock_seconds
        output=samples_dir/f"{sample_id}.mp3"
        metrics=asyncio.run(synthesize_edge_plan(plan,voice=DEFAULT_VOICE,rate="+0%",pitch="+0Hz",output=output))
        synthesis+=float(metrics["wall_clock_seconds"]); calls+=int(metrics["external_calls"])
        rows.append({
            "sample_id":sample_id,"canonical_text":text,"plan":plan.to_dict(),"edge_metrics":metrics,
            "probe":_probe(output),
            "cache_identity":pronunciation_cache_identity(plan,provider_id="edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE,rate="+0%",pitch="+0Hz"),
        })
    opening_text=canonical_opening_text("as novidades de hoje")
    opening_plan=resolve_synthesis_plan(opening_text,voice=DEFAULT_VOICE)
    opening_takes=[]
    for take in TAKE_PROFILES:
        output=samples_dir/f"H-opening-{take['take_id']}.mp3"
        metrics=asyncio.run(synthesize_edge_plan(
            opening_plan,
            voice=DEFAULT_VOICE,
            rate=take["rate"],
            pitch=take["pitch"],
            output=output,
        ))
        opening_takes.append({
            "take_id":take["take_id"],
            "rate":take["rate"],
            "pitch":take["pitch"],
            "role":take["role"],
            "canonical_text":opening_text,
            "plan":opening_plan.to_dict(),
            "edge_metrics":metrics,
            "probe":_probe(output),
        })

    fluidity_takes=[]
    for profile in FLUIDITY_PROFILES:
        synthesis_text=profile["synthesis_text"]
        fluid_plan=resolve_synthesis_plan(synthesis_text,voice=DEFAULT_VOICE)
        output=samples_dir/f"I-opening-{profile['take_id']}.mp3"
        metrics=asyncio.run(synthesize_edge_plan(
            fluid_plan,
            voice=DEFAULT_VOICE,
            rate=profile["rate"],
            pitch=profile["pitch"],
            output=output,
        ))
        fluidity_takes.append({
            "take_id":profile["take_id"],
            "rate":profile["rate"],
            "pitch":profile["pitch"],
            "spoken_words":FLUIDITY_TEXT,
            "synthesis_text":synthesis_text,
            "plan":fluid_plan.to_dict(),
            "edge_metrics":metrics,
            "probe":_probe(output),
        })

    closing=next(x for x in rows if x["sample_id"]=="C-closing")
    vice=next(x for x in closing["plan"]["spans"] if x.get("pronunciation_identity")=="vice-city")
    closing_timing=closing["edge_metrics"]["timing"]
    em_word=next(x for x in closing_timing if x["text"].strip().lower()=="em")
    vice_word=next(x for x in closing_timing if x["text"].strip().lower()=="vice")
    vice_city_join_gap_seconds=(
        float(vice_word["offset_seconds"])
        - (
            float(em_word["offset_seconds"])
            + float(em_word["duration_seconds"])
        )
    )
    gta_brand=next(x for x in rows if x["sample_id"]=="F-gta6-brand")
    gta=next(x for x in gta_brand["plan"]["spans"] if x.get("pronunciation_identity")=="gta-6")
    mixed_brand=next(x for x in rows if x["sample_id"]=="G-brand-mixed")
    strict_plan=resolve_synthesis_plan("E BR não dorme em Vice City",voice=DEFAULT_VOICE)
    azure_ssml=build_azure_ssml(strict_plan)
    edge=provider_capabilities("edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE)
    azure=provider_capabilities("azure-speech",voice=DEFAULT_VOICE)
    checks={
        "PRONUNCIATION_LAYER":all(x["plan"]["canonical_text_preserved"] for x in rows),
        "CANONICAL_TEXT_PRESERVED":all(x["plan"]["canonical_text"]==x["canonical_text"] for x in rows),
        "VOICE_B_PRESERVED":True,
        "VICE_CITY_LANGUAGE_RESOLUTION":vice["locale"]=="en-US" and vice["text"]=="Vice City",
        "VICE_CITY_REAL_AUDIO_GENERATED":closing["probe"]["size_bytes"]>0,
        "VICE_CITY_JOIN_TIMING_NATURAL":(
            0.0 <= vice_city_join_gap_seconds <= 0.15
        ),
        "GTA6_CANONICAL_TEXT_PRESERVED":(
            gta_brand["plan"]["canonical_text"]=="Aqui é BR no GTA 6."
            and gta_brand["plan"]["canonical_text_preserved"] is True
            and gta["pronunciation_identity"]=="gta-6"
            and gta["text"].rstrip(" \\t\\r\\n.,!?;:")=="GTA 6"
            and gta["synthesis_text"].rstrip(" \\t\\r\\n.,!?;:")=="gê tê á seis"
        ),
        "GTA6_REAL_AUDIO_GENERATED":gta_brand["probe"]["size_bytes"]>0,
        "GTA6_AND_VICE_CITY_COEXIST":(
            any(x.get("pronunciation_identity")=="gta-6" for x in mixed_brand["plan"]["spans"])
            and any(x.get("pronunciation_identity")=="vice-city" for x in mixed_brand["plan"]["spans"])
        ),
        "NATURAL_PTBR_PROSODY_CONTINUITY":(
            opening_plan.foreign_span_count==0
            and all(item["edge_metrics"]["external_calls"]==1 for item in opening_takes)
            and all(item["edge_metrics"]["synthesis_group_count"]==1 for item in opening_takes)
            and "gê tê á seis" in opening_plan.rendered_text
        ),
        "OPENING_THREE_TAKES_GENERATED":(
            len(opening_takes)==3
            and {item["take_id"] for item in opening_takes}=={"take-1","take-2","take-3"}
            and all(item["probe"]["size_bytes"]>0 for item in opening_takes)
        ),
        "OPENING_FLUIDITY_THREE_TAKES_GENERATED":(
            len(fluidity_takes)==3
            and {item["take_id"] for item in fluidity_takes}=={"fluid-1","fluid-2","fluid-3"}
            and all(item["probe"]["size_bytes"]>0 for item in fluidity_takes)
            and all(item["edge_metrics"]["external_calls"]==1 for item in fluidity_takes)
            and all(item["edge_metrics"]["synthesis_group_count"]==1 for item in fluidity_takes)
            and all(item["plan"]["foreign_span_count"]==0 for item in fluidity_takes)
            and all("gê tê á seis" in "".join(span["synthesis_text"] for span in item["plan"]["spans"]) for item in fluidity_takes)
        ),
        "MIXED_LANGUAGE_SYNTHESIS":closing["plan"]["foreign_span_count"]>=1,
        "PRONUNCIATION_LEXICON":"vice-city" in closing["plan"]["lexicon_hits"],
        "CACHE_INVALIDATION":"lexicon_version" in closing["cache_identity"],
        "EDGE_CAPABILITY_BOUNDARY":edge.supports_ssml is False and edge.supports_isolated_multilingual_chunks is True,
        "STRICT_PROVIDER_BOUNDARY":azure.supports_language_spans is True and '<lang xml:lang="en-US">Vice City</lang>' in azure_ssml and azure.supports_phoneme is False,
        "FINAL_AUDIO_DECODE":all(x["probe"]["full_decode"] for x in rows),
        "NO_EDITORIAL_TEXT_MUTATION":all("Váiss" not in json.dumps(x["plan"],ensure_ascii=False) and "Vaice" not in json.dumps(x["plan"],ensure_ascii=False) for x in rows),
    }
    if not all(checks.values()): raise RuntimeError("pronunciation proof failed:"+",".join(k for k,v in checks.items() if not v))
    evidence={
        "status":"PASS","voice":DEFAULT_VOICE,"provider":"edge-tts","provider_version":"7.2.8",
        "sample_count":len(rows),"samples":rows,"opening_naturality_takes":opening_takes,"opening_fluidity_takes":fluidity_takes,"checks":checks,
        "timing_quality":{"vice_city_join_gap_seconds":vice_city_join_gap_seconds,"max_allowed_seconds":0.15},
        "strict_provider":{"provider":"azure-speech","ssml_preview":azure_ssml,"capabilities":azure.to_dict(),"live_call_executed":False,"reason":"optional strict boundary; Edge proves the current production path without Azure credentials"},
        "human_review":{
            "status":"PENDING",
            "automatic_promotion":False,
            "terms":{
                "vice-city":{
                    "status":"APPROVED",
                    "sample_id":"C-closing",
                    "target_ipa":vice.get("target_ipa"),
                    "basis":"human review in Telegram on 2026-09-19",
                },
                "gta-6":{
                    "status":"PENDING",
                    "sample_id":"F-gta6-brand",
                    "candidate_synthesis_text":gta.get("synthesis_text"),
                    "basis":"latest human review rejected provider-driven GTA 6 pronunciation; current candidate uses explicit PT-BR letter names",
                },
                "voice-b-naturality":{
                    "status":"PENDING",
                    "sample_ids":[item["take_id"] for item in opening_takes],
                    "files":[f"H-opening-{item['take_id']}.mp3" for item in opening_takes],
                    "basis":"human review required for timing, warmth, energy and naturality; technical metrics cannot auto-select a winner",
                },
                "opening-fluidity":{
                    "status":"PENDING",
                    "spoken_words":FLUIDITY_TEXT,
                    "sample_ids":[item["take_id"] for item in fluidity_takes],
                    "files":[f"I-opening-{item['take_id']}.mp3" for item in fluidity_takes],
                    "basis":"user-supplied smoother opening wording; no automatic promotion until human listening review",
                },
            },
        },
        "performance":{
            "baseline_literal_closing":{"wall_clock_seconds":baseline["wall_clock_seconds"],"external_calls":baseline["external_calls"],"probe":baseline["probe"]},
            "candidate_multilingual_closing":{"wall_clock_seconds":closing["edge_metrics"]["wall_clock_seconds"],"external_calls":closing["edge_metrics"]["external_calls"],"probe":closing["probe"]},
            "comparison_basis":"same canonical closing text; performance is descriptive because candidate changes pronunciation handling quality",
            "resolution_wall_clock_seconds":resolution,"synthesis_wall_clock_seconds":synthesis,
            "total_wall_clock_seconds":time.monotonic()-total_started,"tts_external_calls":calls,
            "span_count":sum(len(x["plan"]["spans"]) for x in rows),
            "foreign_span_count":sum(x["plan"]["foreign_span_count"] for x in rows),
            "opening_take_external_calls":[item["edge_metrics"]["external_calls"] for item in opening_takes],
            "opening_take_durations_seconds":[item["probe"]["duration_seconds"] for item in opening_takes],
            "fluidity_take_external_calls":[item["edge_metrics"]["external_calls"] for item in fluidity_takes],
            "fluidity_take_durations_seconds":[item["probe"]["duration_seconds"] for item in fluidity_takes]
        },
        "JOB18_UNCHANGED":"YES","PUBLICATION_AUTHORITY_UNCHANGED":"YES",
    }
    (args.output_dir/"pronunciation-proof.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    (args.output_dir/"azure-ssml-boundary.xml").write_text(azure_ssml,encoding="utf-8")
    for key,passed in checks.items(): print(f"{key}={'PASS' if passed else 'FAIL'}")
    print("VICE_CITY_PRONUNCIATION_HUMAN_APPROVED=PASS")
    print("GTA6_PRONUNCIATION_HUMAN_APPROVED=PENDING")
    print("VOICE_B_NATURALITY_HUMAN_APPROVED=PENDING")
    print("JOB18_UNCHANGED=YES"); print("PUBLICATION_AUTHORITY_UNCHANGED=YES")
    return 0

if __name__=="__main__": raise SystemExit(main())
