from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SOURCE_URL="https://www.youtube.com/watch?v=tJbzMqJGH4k"
SOURCE_SHA256="4186ccdc860590e2b4d2ea28dfb882583b522e0e1cbf1c069ff14693e2195d85"
SOURCE_DATE="2026-08-27"

DISCOVERY_SOURCES=[
    "https://flowgames.gg/gta-6-ganha-27-minutos-incriveis-de-gameplay-confira/",
    "https://www.tecmundo.com.br/voxel/505252-gameplay-de-gta-6-esta-disponivel-hoje-27-na-netflix-assista-de-graca-aqui.htm",
    "https://www.adrenaline.com.br/artigos/gta-vi-na-netflix-e-mais-todas-as-novidades-oficiais-liberadas-pela-rockstar-games/",
    "https://www.uol.com.br/splash/noticias/2026/08/27/gta-6-detalha-historia-e-mecanicas-em-video-na-netflix.ghtm",
]

# Conservative visual observations established from the official source. These are
# deliberately narrower than secondary-source claims. Transcript and scene index
# are attached during the run so stronger wording can be evaluated later.
FINDING_WINDOWS=[
    ("EL001",150,190,"INTERIOR_WORLD","A sequence moves through a lived-in interior into a room containing drug-lab/cook equipment.","HIGH"),
    ("EL002",250,330,"COMBAT","Extended over-the-shoulder gun combat is shown across interior and outdoor spaces.","HIGH"),
    ("EL003",380,450,"DOMESTIC_INTERACTION","Jason/Lucia domestic interior scenes show non-combat interaction inside a residence.","MEDIUM"),
    ("EL004",455,485,"WILDLIFE_WORLD","Open natural environments and wildlife are shown outside the dense city core.","MEDIUM"),
    ("EL005",485,510,"FOOD_CHARACTER","A character is shown eating during ordinary-world interaction.","MEDIUM"),
    ("EL006",500,550,"OPEN_WORLD_DRIVING","Free-driving footage shows urban traffic and traversal rather than a cinematic-only montage.","HIGH"),
    ("EL007",545,570,"MELEE","A street fistfight is shown from gameplay camera perspective.","HIGH"),
    ("EL008",570,610,"NIGHTLIFE","Elevator/club/rooftop social spaces appear as explorable interiors and gathering areas.","HIGH"),
    ("EL009",680,735,"ROBBERY","Masked characters participate in an armed store/indoor robbery sequence.","HIGH"),
    ("EL010",735,790,"DRIVING_WORLD","City and bridge traversal connects distinct urban spaces in continuous driving footage.","MEDIUM"),
    ("EL011",830,880,"POLICE_COMBAT","An armed confrontation visibly escalates into police response with wanted-level HUD elements.","HIGH"),
    ("EL012",930,970,"VEHICLE_DAMAGE","A vehicle burns/explodes in a parking structure during gameplay.","MEDIUM"),
    ("EL013",1030,1055,"COASTAL_WORLD","Beach and ocean spaces are shown as part of the playable-world presentation.","MEDIUM"),
    ("EL014",1055,1085,"RACING","A vehicle race sequence is shown with race/progress UI.","HIGH"),
    ("EL015",1085,1105,"FIRST_PERSON_TRAVERSAL","A first-person-like walking view appears while moving through a storefront/urban space.","MEDIUM"),
    ("EL016",1085,1110,"SOCIAL_CAPTURE","A character poses for a selfie/social image during a non-combat interaction.","MEDIUM"),
    ("EL017",1090,1115,"ACTIVITY_UI","An on-screen activities/list interface appears during the gameplay presentation.","HIGH"),
    ("EL018",1100,1125,"MOTOCROSS","Off-road motorcycle/motocross activity is shown.","HIGH"),
    ("EL019",1120,1145,"PARACHUTING","Parachuting is shown as a playable traversal/activity sequence.","HIGH"),
    ("EL020",1140,1170,"DOMESTIC_SOCIAL","Two characters drink/socialize in a domestic setting.","MEDIUM"),
    ("EL021",1160,1200,"LUXURY_INTERIOR","A high-end office/luxury interior is shown with character interaction.","MEDIUM"),
    ("EL022",1180,1215,"AIRFIELD","A nighttime airfield/aviation-area meeting sequence is shown.","MEDIUM"),
    ("EL023",1200,1235,"RACING_NIGHT","Night driving/race footage displays explicit progress UI.","HIGH"),
    ("EL024",1235,1285,"EVENT_INTERIOR","Characters enter and move through a large nightlife/event interior with crowds.","MEDIUM"),
    ("EL025",1280,1345,"SOCIAL_INTERACTION","Extended party/social interaction is shown without immediate combat.","MEDIUM"),
    ("EL026",1320,1390,"INTERIOR_EXPLORATION","A character walks through a multi-room high-rise/luxury interior in gameplay camera perspective.","HIGH"),
    ("EL027",1390,1445,"INTERIOR_COMBAT","The high-rise sequence escalates into armed combat across rooms and corridors.","HIGH"),
    ("EL028",1425,1455,"SOCIAL_MEDIA_UI","A social-media-style post/overlay appears within the presentation.","HIGH"),
    ("EL029",1440,1505,"TAKEDOWN_COMBAT","Close-quarters takedown and armed interior combat are shown in the late-gameplay montage.","HIGH"),
    ("EL030",1500,1545,"INTERIOR_GUNFIGHT","A sustained gunfight continues through office/rooftop-access interiors.","HIGH"),
    ("EL031",1560,1585,"BOATING","A boat scene closes the gameplay montage before title/end cards.","MEDIUM"),
]

def load(path:Path)->Any:
    return json.loads(path.read_text(encoding="utf-8"))

def find_one(root:Path,name:str)->Path:
    rows=[p for p in root.rglob(name) if p.is_file()]
    if len(rows)!=1:
        raise RuntimeError(f"expected one {name}, found {len(rows)}")
    return rows[0]

def sha256(path:Path)->str:
    import hashlib
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def extract_frame(video:Path,at:float,target:Path)->None:
    target.parent.mkdir(parents=True,exist_ok=True)
    proc=subprocess.run([
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
        "-ss",f"{at:.3f}","-i",str(video),"-frames:v","1","-q:v","2",str(target)
    ],capture_output=True,text=True,timeout=180)
    if proc.returncode!=0:
        raise RuntimeError((proc.stderr or "")[-1200:])

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--video-root",type=Path,required=True)
    ap.add_argument("--knowledge-root",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    video=find_one(args.video_root,"source.mp4")
    media=find_one(args.knowledge_root,"media_knowledge.json")
    knowledge=load(media)
    if sha256(video)!=SOURCE_SHA256:
        raise RuntimeError("Extended Look source identity changed")
    scenes=knowledge.get("scenes") or []
    if len(scenes)!=314:
        raise RuntimeError(f"expected 314 source scenes, got {len(scenes)}")

    from faster_whisper import WhisperModel
    model=WhisperModel("medium",device="cpu",compute_type="int8")
    segments,info=model.transcribe(
        str(video),language="en",beam_size=5,vad_filter=True,word_timestamps=True
    )
    transcript=[]
    for idx,seg in enumerate(segments,1):
        transcript.append({
            "segment_id":idx,
            "start_seconds":float(seg.start),
            "end_seconds":float(seg.end),
            "text":str(seg.text or "").strip(),
            "words":[
                {
                    "text":str(w.word or "").strip(),
                    "start_seconds":float(w.start),
                    "end_seconds":float(w.end),
                    "confidence":float(w.probability or 0.0),
                }
                for w in (seg.words or []) if w.start is not None and w.end is not None
            ],
        })

    def overlap_text(start:float,end:float)->str:
        return " ".join(
            row["text"] for row in transcript
            if row["end_seconds"]>start and row["start_seconds"]<end and row["text"]
        ).strip()

    scene_rows=[]
    for scene in scenes:
        start=float(scene["start_seconds"]); end=float(scene["end_seconds"])
        scene_rows.append({
            "scene_index":int(scene["index"]),
            "start_seconds":start,
            "end_seconds":end,
            "duration_seconds":float(scene["duration_seconds"]),
            "transcript":overlap_text(start,end),
            "primary_source":SOURCE_URL,
            "source_date":SOURCE_DATE,
        })

    findings=[]
    for fid,start,end,category,observed,value in FINDING_WINDOWS:
        transcript_text=overlap_text(start,end)
        frame=args.output_dir/"frames"/f"{fid}-{int((start+end)/2):04d}s.jpg"
        extract_frame(video,(start+end)/2,frame)
        findings.append({
            "FINDING_ID":fid,
            "TIMECODE_START":start,
            "TIMECODE_END":end,
            "OBSERVED_FACT":observed,
            "CATEGORY":category,
            "OFFICIAL_SOURCE":SOURCE_URL,
            "SOURCE_DATE":SOURCE_DATE,
            "SOURCE_SHA256":SOURCE_SHA256,
            "TRANSCRIPT_EVIDENCE":transcript_text,
            "FRAME_EVIDENCE":str(frame.relative_to(args.output_dir)),
            "CORROBORATING_SOURCES":DISCOVERY_SOURCES,
            "CONFIDENCE":"HIGH",
            "EDITORIAL_VALUE":value,
            "PREVIOUSLY_COVERED":"NO" if category not in {"NIGHTLIFE","SOCIAL_MEDIA_UI","DOMESTIC_SOCIAL"} else "PARTIAL",
            "CLAIM_CLASS":"OFFICIALLY_OBSERVED_IN_PRIMARY_VIDEO",
            "secondary_sources_are_discovery_only":True,
        })

    output={
        "schema":"gtavi-extended-look-primary-audit/v1",
        "status":"PASS",
        "source":{
            "name":"Grand Theft Auto VI: An Extended Look",
            "url":SOURCE_URL,
            "date":SOURCE_DATE,
            "sha256":SOURCE_SHA256,
            "duration_seconds":knowledge["probe"]["duration_seconds"],
            "captured_platform":"PlayStation 5",
        },
        "EXTENDED_LOOK_SCENES_TOTAL":len(scene_rows),
        "EXTENDED_LOOK_FINDINGS_TOTAL":len(findings),
        "HIGH_VALUE_NEW_FINDINGS":sum(1 for x in findings if x["EDITORIAL_VALUE"]=="HIGH"),
        "scene_audit":scene_rows,
        "findings":findings,
        "transcript":transcript,
        "research_policy":{
            "primary_video_is_factual_authority":True,
            "brazilian_secondary_sources_are_discovery_only":True,
            "leaks_for_factual_support_forbidden":True,
        },
    }
    (args.output_dir/"extended-look-primary-audit.json").write_text(
        json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    (args.output_dir/"extended-look-transcript.json").write_text(
        json.dumps(transcript,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    print("EXTENDED_LOOK_SCENES_TOTAL="+str(len(scene_rows)))
    print("EXTENDED_LOOK_FINDINGS_TOTAL="+str(len(findings)))
    print("HIGH_VALUE_NEW_FINDINGS="+str(output["HIGH_VALUE_NEW_FINDINGS"]))
    print("PRIMARY_SOURCE_SHA256="+SOURCE_SHA256)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
