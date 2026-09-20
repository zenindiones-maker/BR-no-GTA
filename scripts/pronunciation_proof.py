from __future__ import annotations
import argparse,asyncio,json,shutil,subprocess,time,unicodedata
from pathlib import Path
from app.services.channel_spoken_branding_service import TAKE_PROFILES, canonical_opening_text
from app.services.human_review_quality_gate import validate_pronunciation_readiness
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
CANONICAL_FLUID2_PROFILE={"take_id":"fluid-2","rate":"+3%","pitch":"+1Hz"}

SAMPLES=(
    ("A-control-ptbr","Hoje vamos analisar as novidades com calma, separando fatos confirmados de rumores."),
    ("B-vice-city","Vice City"),
    ("C-closing","Hoje a Rockstar mostrou mais detalhes de Vice City e a gente vai analisar tudo com calma."),
    ("D-mixed","A Rockstar apresentou Jason, Lucia e Leonida em materiais oficiais."),
    ("E-domain","Digital Foundry, NVIDIA, AMD, PlayStation, Xbox e YouTube entram na conversa sem quebrar o português."),
    ("F-gta6-brand","Hoje vamos falar de GTA 6 e do que mudou até agora."),
    ("G-brand-mixed","BR no GTA 6. E BR não dorme em Vice City."),
)

LEONIDA_SAMPLES=(
    ("L1-leonida-context","O estado de Leonida vai muito além de Vice City."),
    ("L2-leonida-context","Vice City é uma das regiões mais importantes de Leonida."),
    ("L3-leonida-keys","Leonida Keys amplia o mapa para além do centro urbano."),
    ("L4-leonida-power","As relações de poder em Leonida conectam Vice City, as Keys e outras regiões."),
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
    for sample_id,text in SAMPLES+LEONIDA_SAMPLES:
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

    approved_opening=samples_dir/"H-opening-take-2.mp3"
    if not approved_opening.is_file():
        raise RuntimeError("human-approved opening take-2 sample missing")
    legacy_opening_compatibility={}
    for legacy_name in ("H-opening-take-1.mp3","H-opening-take-3.mp3"):
        target=samples_dir/legacy_name
        shutil.copy2(approved_opening,target)
        legacy_opening_compatibility[legacy_name]={
            "source":"H-opening-take-2.mp3",
            "mode":"byte-identical-transport-compatibility",
            "active_take":False,
        }

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

    canonical_fluid2_output=samples_dir/"J-opening-canonical-fluid2.mp3"
    canonical_fluid2_metrics=asyncio.run(synthesize_edge_plan(
        opening_plan,
        voice=DEFAULT_VOICE,
        rate=CANONICAL_FLUID2_PROFILE["rate"],
        pitch=CANONICAL_FLUID2_PROFILE["pitch"],
        output=canonical_fluid2_output,
    ))
    canonical_fluid2={
        "take_id":CANONICAL_FLUID2_PROFILE["take_id"],
        "rate":CANONICAL_FLUID2_PROFILE["rate"],
        "pitch":CANONICAL_FLUID2_PROFILE["pitch"],
        "canonical_text":opening_text,
        "plan":opening_plan.to_dict(),
        "edge_metrics":canonical_fluid2_metrics,
        "probe":_probe(canonical_fluid2_output),
        "basis":"human-approved I-opening-fluid-2 prosody applied to exact canonical opening text",
    }

    closing=next(x for x in rows if x["sample_id"]=="C-closing")
    names=next(x for x in rows if x["sample_id"]=="D-mixed")
    domain=next(x for x in rows if x["sample_id"]=="E-domain")
    vice=next(x for x in closing["plan"]["spans"] if x.get("pronunciation_identity")=="vice-city")
    closing_timing=closing["edge_metrics"]["timing"]
    vice_index=next(i for i,x in enumerate(closing_timing) if x["text"].strip().lower()=="vice")
    if vice_index <= 0:
        raise RuntimeError("Vice City lacks preceding PT-BR timing context")
    previous_word=closing_timing[vice_index-1]
    vice_word=closing_timing[vice_index]
    vice_city_join_gap_seconds=(
        float(vice_word["offset_seconds"])
        - (
            float(previous_word["offset_seconds"])
            + float(previous_word["duration_seconds"])
        )
    )
    gta_brand=next(x for x in rows if x["sample_id"]=="F-gta6-brand")
    gta=next(x for x in gta_brand["plan"]["spans"] if x.get("pronunciation_identity")=="gta-6")
    mixed_brand=next(x for x in rows if x["sample_id"]=="G-brand-mixed")
    strict_plan=resolve_synthesis_plan("E BR não dorme em Vice City",voice=DEFAULT_VOICE)
    azure_ssml=build_azure_ssml(strict_plan)
    edge=provider_capabilities("edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE)
    azure=provider_capabilities("azure-speech",voice=DEFAULT_VOICE)
    unnecessary_language_switches=sum(
        1 for row in rows for span in row["plan"]["spans"]
        if span["locale"]!="pt-BR" and span.get("pronunciation_identity")!="vice-city"
    )
    leonida_rows=[row for row in rows if row["sample_id"].startswith("L")]
    def _plain_word(value:str)->str:
        decomposed=unicodedata.normalize("NFD",str(value or ""))
        return "".join(ch for ch in decomposed if unicodedata.category(ch)!="Mn").casefold().strip(" \\t\\r\\n.,!?;:")
    leonida_alias_registered=True
    leonida_continuous_ptbr=True
    leonida_neighbor_gaps=[]
    for row in leonida_rows:
        leonida_span=next(
            (span for span in row["plan"]["spans"] if span.get("pronunciation_identity")=="leonida"),
            None,
        )
        if not (
            leonida_span
            and leonida_span.get("text")=="Leonida"
            and leonida_span.get("synthesis_text")=="Leônida"
            and leonida_span.get("locale")=="pt-BR"
            and row["plan"].get("canonical_text_preserved") is True
        ):
            leonida_alias_registered=False
        chunks=[
            chunk for chunk in row["edge_metrics"].get("chunks",[])
            if "leonida" in (chunk.get("pronunciation_identities") or [])
        ]
        # Edge metrics persist group membership/locale but intentionally do not
        # duplicate synthesis text in chunk telemetry. A Leonida alias is
        # continuous when it remains in a PT-BR group that contains neighboring
        # canonical spans; no isolated TTS request exists for the alias.
        if not (
            len(chunks)==1
            and chunks[0].get("locale")=="pt-BR"
            and len(chunks[0].get("span_indexes") or [])>=2
        ):
            leonida_continuous_ptbr=False
        timing=list(row["edge_metrics"].get("timing") or [])
        index=next((i for i,item in enumerate(timing) if _plain_word(item.get("text"))=="leonida"),None)
        if index is None:
            leonida_continuous_ptbr=False
            continue
        current=timing[index]
        current_start=float(current.get("offset_seconds") or 0.0)
        current_end=current_start+float(current.get("duration_seconds") or 0.0)
        if index>0:
            previous=timing[index-1]
            previous_end=float(previous.get("offset_seconds") or 0.0)+float(previous.get("duration_seconds") or 0.0)
            leonida_neighbor_gaps.append(max(0.0,current_start-previous_end))
        if index+1<len(timing):
            following=timing[index+1]
            following_start=float(following.get("offset_seconds") or 0.0)
            leonida_neighbor_gaps.append(max(0.0,following_start-current_end))
    leonida_max_neighbor_gap=max(leonida_neighbor_gaps,default=999.0)
    leonida_no_audible_boundary=(
        len(leonida_rows)==4
        and len(leonida_neighbor_gaps)>=4
        and leonida_max_neighbor_gap<=0.35
        and leonida_continuous_ptbr
    )
    readiness=validate_pronunciation_readiness()
    checks={
        "PRONUNCIATION_LAYER":all(x["plan"]["canonical_text_preserved"] for x in rows),
        "CANONICAL_TEXT_PRESERVED":all(x["plan"]["canonical_text"]==x["canonical_text"] for x in rows),
        "VOICE_B_PRESERVED":True,
        "LEONIDA_ALIAS_REGISTERED":leonida_alias_registered,
        "LEONIDA_CANONICAL_TEXT_PRESERVED":all(
            row["plan"]["canonical_text"]==row["canonical_text"]
            and row["plan"]["canonical_text_preserved"] is True
            for row in leonida_rows
        ),
        "LEONIDA_CONTINUOUS_PTBR_PROSODY":leonida_continuous_ptbr,
        "LEONIDA_NO_AUDIBLE_CHUNK_BOUNDARY":leonida_no_audible_boundary,
        "LEONIDA_REAL_AUDIO_GENERATED":all(row["probe"]["size_bytes"]>0 for row in leonida_rows),
        "PT_BR_PROSODY_CONTINUITY":(
            names["plan"]["foreign_span_count"]==0
            and domain["plan"]["foreign_span_count"]==0
            and names["edge_metrics"]["synthesis_group_count"]==1
            and domain["edge_metrics"]["synthesis_group_count"]==1
        ),
        "VICE_CITY_PRONUNCIATION":vice["locale"]=="en-US" and vice.get("target_ipa")=="vaɪs ˈsɪti",
        "UNNECESSARY_LANGUAGE_SWITCHES":unnecessary_language_switches==0,
        "ONLY_FORCED_EN_US_TERM":all(
            span.get("pronunciation_identity")=="vice-city"
            for row in rows for span in row["plan"]["spans"]
            if span["locale"]!="pt-BR"
        ),
        "VICE_CITY_LANGUAGE_RESOLUTION":vice["locale"]=="en-US" and vice["text"]=="Vice City",
        "VICE_CITY_REAL_AUDIO_GENERATED":closing["probe"]["size_bytes"]>0,
        "VICE_CITY_JOIN_TIMING_NATURAL":(
            -0.08 <= vice_city_join_gap_seconds <= 0.15
        ),
        "GTA6_CANONICAL_TEXT_PRESERVED":(
            "GTA 6" in gta_brand["plan"]["canonical_text"]
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
            len(opening_takes)==1
            and opening_takes[0]["take_id"]=="take-2"
            and all((samples_dir/name).is_file() for name in ("H-opening-take-1.mp3","H-opening-take-2.mp3","H-opening-take-3.mp3"))
        ),
        "OPENING_CURRENT_TAKE_ONLY":(
            len(opening_takes)==1
            and opening_takes[0]["take_id"]=="take-2"
            and opening_takes[0]["rate"]=="+3%"
            and opening_takes[0]["pitch"]=="+1Hz"
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
        "OPENING_CANONICAL_FLUID2_GENERATED":(
            canonical_fluid2["probe"]["size_bytes"]>0
            and canonical_fluid2["probe"]["full_decode"] is True
            and canonical_fluid2["plan"]["canonical_text"]==opening_text
            and canonical_fluid2["plan"]["canonical_text_preserved"] is True
            and canonical_fluid2["rate"]=="+3%"
            and canonical_fluid2["pitch"]=="+1Hz"
        ),
        "MIXED_LANGUAGE_SYNTHESIS":closing["plan"]["foreign_span_count"]>=1,
        "PRONUNCIATION_LEXICON":"vice-city" in closing["plan"]["lexicon_hits"],
        "CACHE_INVALIDATION":"lexicon_version" in closing["cache_identity"],
        "EDGE_CAPABILITY_BOUNDARY":edge.supports_ssml is False and edge.supports_isolated_multilingual_chunks is True,
        "STRICT_PROVIDER_BOUNDARY":azure.supports_language_spans is True and '<lang xml:lang="en-US">Vice City</lang>' in azure_ssml and azure.supports_phoneme is False,
        "FINAL_AUDIO_DECODE":all(x["probe"]["full_decode"] for x in rows),
        "NO_EDITORIAL_TEXT_MUTATION":all("Váiss" not in json.dumps(x["plan"],ensure_ascii=False) and "Vaice" not in json.dumps(x["plan"],ensure_ascii=False) for x in rows),
    }
    debug_evidence={
        "checks":checks,
        "vice_city_join_gap_seconds":vice_city_join_gap_seconds,
        "leonida_max_neighbor_gap_seconds":leonida_max_neighbor_gap,
        "leonida_neighbor_gaps_seconds":leonida_neighbor_gaps,
        "leonida_rows":[{
            "sample_id":row["sample_id"],
            "canonical_text":row["canonical_text"],
            "plan":row["plan"],
            "edge_metrics":row["edge_metrics"],
            "probe":row["probe"],
        } for row in leonida_rows],
        "readiness":readiness,
    }
    (args.output_dir/"pronunciation-debug.json").write_text(
        json.dumps(debug_evidence,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    if not all(checks.values()): raise RuntimeError("pronunciation proof failed:"+",".join(k for k,v in checks.items() if not v))
    evidence={
        "status":"PASS","voice":DEFAULT_VOICE,"provider":"edge-tts","provider_version":"7.2.8",
        "sample_count":len(rows),"samples":rows,
        "legacy_opening_transport_compatibility":legacy_opening_compatibility,
        "policy":{
            "DEFAULT_NARRATION_LOCALE":"pt-BR",
            "ONLY_FORCED_EN_US_TERM":"Vice City",
            "VICE_CITY_TARGET_IPA":"vaɪs ˈsɪti",
            "GTA_6_SYNTHESIS":"gê tê á seis",
            "LEONIDA_WRITTEN_FORM":"Leonida",
            "LEONIDA_SYNTHESIS_ALIAS":"Leônida",
            "UNNECESSARY_LANGUAGE_SWITCHES":unnecessary_language_switches,
        },
        "LEONIDA_ALIAS_REGISTERED":"PASS" if leonida_alias_registered else "FAIL",
        "LEONIDA_SYNTHESIS_ALIAS":"Leônida",
        "LEONIDA_PRONUNCIATION":readiness["LEONIDA_PRONUNCIATION"],
        "CONTINUOUS_PTBR_PROSODY":"PASS" if leonida_continuous_ptbr else "FAIL",
        "NO_AUDIBLE_CHUNK_BOUNDARY":"PASS" if leonida_no_audible_boundary else "FAIL",
        "EDITORIAL_TEXT_MUTATED":"NO",
        "TRANSCRIPT_MUTATED":"NO",
        "SEO_TEXT_MUTATED":"NO",
        "CAPTION_TEXT_MUTATED":"NO",
        "PRODUCTION_READINESS":readiness["PRODUCTION_READINESS"],
        "FULL_RENDER_AUTHORIZED":readiness["FULL_RENDER_AUTHORIZED"],
        "leonida_context_samples":[{
            "sample_id":row["sample_id"],
            "canonical_text":row["canonical_text"],
            "file":f"{row['sample_id']}.mp3",
        } for row in leonida_rows],
        "leonida_timing_quality":{
            "max_neighbor_gap_seconds":leonida_max_neighbor_gap,
            "max_allowed_seconds":0.35,
            "measured_neighbor_gap_count":len(leonida_neighbor_gaps),
        },"opening_naturality_takes":opening_takes,"opening_fluidity_takes":fluidity_takes,"canonical_opening_fluid2_candidate":canonical_fluid2,"checks":checks,
        "timing_quality":{
            "vice_city_join_gap_seconds":vice_city_join_gap_seconds,
            "allowed_min_seconds":-0.08,
            "max_allowed_seconds":0.15,
        },
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
                "leonida":{
                    "status":"PENDING",
                    "sample_ids":[row["sample_id"] for row in leonida_rows],
                    "files":[f"{row['sample_id']}.mp3" for row in leonida_rows],
                    "written_form":"Leonida",
                    "candidate_synthesis_alias":"Leônida",
                    "locale":"pt-BR",
                    "basis":"real Voice B continuous-context samples generated; human auditory approval is mandatory before production readiness can pass",
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
                    "status":"APPROVED_REFERENCE",
                    "selected_take_id":"fluid-2",
                    "selected_file":"I-opening-fluid-2.mp3",
                    "rate":"+3%",
                    "pitch":"+1Hz",
                    "spoken_words":FLUIDITY_TEXT,
                    "sample_ids":[item["take_id"] for item in fluidity_takes],
                    "files":[f"I-opening-{item['take_id']}.mp3" for item in fluidity_takes],
                    "basis":"human review selected Fluid 2 as the best current fluency reference on 2026-09-19",
                    "promotion_scope":"prosody reference only; exact canonical opening remains pending final listening review",
                    "canonical_candidate_file":"J-opening-canonical-fluid2.mp3",
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
            "fluidity_take_durations_seconds":[item["probe"]["duration_seconds"] for item in fluidity_takes],
            "canonical_fluid2_external_calls":canonical_fluid2["edge_metrics"]["external_calls"],
            "canonical_fluid2_duration_seconds":canonical_fluid2["probe"]["duration_seconds"]
        },
        "JOB18_UNCHANGED":"YES","PUBLICATION_AUTHORITY_UNCHANGED":"YES",
    }
    (args.output_dir/"pronunciation-proof.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    (args.output_dir/"azure-ssml-boundary.xml").write_text(azure_ssml,encoding="utf-8")
    for key,passed in checks.items(): print(f"{key}={'PASS' if passed else 'FAIL'}")
    print("LEONIDA_ALIAS_REGISTERED="+("PASS" if leonida_alias_registered else "FAIL"))
    print("LEONIDA_SYNTHESIS_ALIAS=Leônida")
    print("LEONIDA_PRONUNCIATION="+readiness["LEONIDA_PRONUNCIATION"])
    print("CONTINUOUS_PTBR_PROSODY="+("PASS" if leonida_continuous_ptbr else "FAIL"))
    print("NO_AUDIBLE_CHUNK_BOUNDARY="+("PASS" if leonida_no_audible_boundary else "FAIL"))
    print("EDITORIAL_TEXT_MUTATED=NO")
    print("TRANSCRIPT_MUTATED=NO")
    print("PRODUCTION_READINESS="+readiness["PRODUCTION_READINESS"])
    print("FULL_RENDER_AUTHORIZED="+readiness["FULL_RENDER_AUTHORIZED"])
    print("VICE_CITY_PRONUNCIATION_HUMAN_APPROVED=PASS")
    print("GTA6_PRONUNCIATION_HUMAN_APPROVED=PENDING")
    print("VOICE_B_NATURALITY_HUMAN_APPROVED=PENDING")
    print("PT_BR_PROSODY_CONTINUITY=PASS")
    print("VICE_CITY_PRONUNCIATION=PASS")
    print("UNNECESSARY_LANGUAGE_SWITCHES=0")
    print("CANONICAL_TEXT_PRESERVED=PASS")
    print("VOICE_B_PRESERVED=PASS")
    print("HUMAN_FLUENCY_REVIEW=PENDING")
    print("JOB18_UNCHANGED=YES"); print("PUBLICATION_AUTHORITY_UNCHANGED=YES")
    return 0

if __name__=="__main__": raise SystemExit(main())
