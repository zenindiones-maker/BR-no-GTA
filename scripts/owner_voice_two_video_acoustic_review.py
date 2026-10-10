#!/usr/bin/env python3
"""Private phonetic-review excerpts from already completed ASR only.

No ASR rerun, model download, Telegram sends, training, owner clone
conditioning, publication, or active lexicon changes.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata

CODESPACE="br-v23-recovery-gxp67g5g7wphwxjw"
REPO="zenindiones-maker/BR-no-GTA"
FILES={
    "f8IZhKcuEts":"b4e981094e468a2ca5f5d270ff2a5338187df935a8d177971a2640bcc28f34be",
    "K6rVM6gn6k4":"ec4645c92e41be73a077f33f04159e45b9abc35c7843d5c7a35be7ccd75a1e52",
}
TARGETS=("GTA 6","Vice City","Leonida","Rockstar")
MAX_PER_TARGET_SOURCE=3

class ReviewBlocked(Exception):
    pass

def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(1048576),b""):
            h.update(block)
    return h.hexdigest()

def safe_json(path):
    if Path(path).is_symlink():
        raise ReviewBlocked("UNTRUSTED_SYMLINK_INPUT")
    def no_constant(_):
        raise ReviewBlocked("NONFINITE_REPORT_VALUE")
    with open(path,encoding="utf-8") as f:
        return json.load(f,parse_constant=no_constant)

def word_norm(word):
    word=unicodedata.normalize("NFC",word).casefold().strip()
    return re.sub(r"^[^\w]+|[^\w]+$","",word,flags=re.UNICODE)

def validate_receipt(evidence):
    run=safe_json(evidence/"run-state.json")
    coverage=safe_json(evidence/"coverage-quality.json")
    report=safe_json(evidence/"candidate-report.json")
    named=safe_json(evidence/"named-phrase-candidates.json")
    if not (
        run.get("status")=="COMPLETE_ASR_UNVERIFIED"
        and run.get("videos_processed")==2
        and report.get("schema")=="OwnerVoiceTwoVideoASR/v3"
        and report.get("status")=="ASR_UNVERIFIED"
        and report.get("speaker_reference_allowed") is False
        and report.get("runtime_activation") is False
        and report.get("human_approval")=="PENDING"
        and coverage.get("status")=="ASR_UNVERIFIED"
        and coverage.get("acoustic_pronunciations_verified")==0
        and named.get("status")=="ACOUSTIC_REVIEW_PENDING"
        and named.get("preference_is_video_verified") is False
        and run.get("unique_words")==coverage.get("unique_words")
        and run.get("total_occurrences")==coverage.get("total_occurrences")
        and len(report.get("videos",[]))==2
    ):
        raise ReviewBlocked("FINAL_ASR_RECEIPT_MISMATCH")
    videos={v.get("video_id"):v for v in report["videos"]}
    if set(videos)!=set(FILES) or len(videos)!=2:
        raise ReviewBlocked("TWO_HASH_PINNED_VIDEOS_REQUIRED")
    for vid,v in videos.items():
        if not (v.get("media_sha256")==FILES[vid] and v.get("language")=="pt"
                and type(v.get("duration_ms")) is int and v["duration_ms"]>0
                and v.get("segments")):
            raise ReviewBlocked("VIDEO_PROVENANCE_FAILED")
    if not isinstance(named.get("candidates"),list):
        raise ReviewBlocked("INVALID_NAMED_CANDIDATES")
    return videos,named

def evaluate_candidate(c,videos):
    """Every accepted item remains HUMAN REVIEW PENDING."""
    if not isinstance(c,dict):
        return "INVALID_CANDIDATE",None
    label,vid=c.get("canonical_text"),c.get("video_id")
    if label not in TARGETS or vid not in videos:
        return "UNKNOWN_PHRASE_OR_SOURCE",None
    v=videos[vid]
    if not (
        c.get("media_sha256")==FILES[vid]
        and c.get("verified_pronunciation") is None
        and c.get("acoustic_review")=="PENDING"
        and c.get("human_approval")=="PENDING"
    ):
        return "PROVENANCE_OR_APPROVAL_MISMATCH",None
    a,b=c.get("start_ms"),c.get("end_ms")
    duration=v["duration_ms"]
    if type(a) is not int or type(b) is not int or not 0<=a<b<=duration:
        return "OUT_OF_MEDIA_OR_INVALID_TIMING",None
    if not 90<=b-a<=4000:
        return "IMPLAUSIBLE_PHRASE_DURATION",None
    if c.get("uncertainty_flags"):
        return "ASR_UNCERTAINTY",None
    n=c.get("segment_index")
    if type(n) is not int or not 0<=n<len(v["segments"]):
        return "SEGMENT_NOT_FOUND",None
    seg=v["segments"][n]
    ws=seg.get("words") or []
    raw=c.get("asr_phrase")
    if not isinstance(raw,str) or not raw.strip():
        return "EMPTY_ASR_PHRASE",None
    want=tuple(word_norm(x) for x in raw.split())
    groups=[]
    for pos in range(len(ws)-len(want)+1):
        g=ws[pos:pos+len(want)]
        if (tuple(word_norm(w.get("text","")) for w in g)==want
            and g[0].get("start_ms")==a and g[-1].get("end_ms")==b):
            groups.append(g)
    if len(groups)!=1:
        return "ASR_SEGMENT_PROVENANCE_MISMATCH",None
    words=groups[0]
    for w in words:
        wa,wb=w.get("start_ms"),w.get("end_ms")
        p=w.get("probability")
        if w.get("timing_status","ALIGNED")!="ALIGNED":
            return "WORD_ALIGNMENT_UNVERIFIED",None
        if type(wa) is not int or type(wb) is not int or not a<=wa<wb<=b:
            return "WORD_INTERVAL_INVALID",None
        if type(p) not in (int,float) or not .65<=p<=1.0:
            return "WORD_CONFIDENCE_LOW_OR_MISSING",None
    logp=seg.get("avg_logprob")
    if type(logp) not in (int,float) or not -1.0<=logp<=0.0:
        return "SEGMENT_CONFIDENCE_LOW_OR_MISSING",None
    nospeech=seg.get("no_speech_prob")
    if nospeech is not None and (type(nospeech) not in (int,float) or nospeech>.6):
        return "NON_SPEECH_RISK",None
    return "CANDIDATE_REVIEW",{
        "target":label,"video_id":vid,"media_sha256":FILES[vid],
        "start_ms":a,"end_ms":b,
        "clip_start_ms":max(0,a-350),"clip_end_ms":min(duration,b+550),
        "min_word_probability":round(min(w["probability"] for w in words),6),
        "segment_index":n,
        "timing_quality":"ASR_ALIGNED_NOT_ACOUSTICALLY_VERIFIED",
        "source_speaker_identity":"NOT_BR_OWNER_V1",
        "acoustic_review":"PENDING","human_approval":"PENDING",
        "speaker_reference_allowed":False,
    }

def choose_candidates(videos,named):
    admissible,rejected=[],[]
    for idx,c in enumerate(named["candidates"]):
        reason,item=evaluate_candidate(c,videos)
        if item is None:
            rejected.append({"candidate_index":idx,"reason":reason})
        else:
            admissible.append(item|{"candidate_index":idx})
    admissible.sort(key=lambda x:(-x["min_word_probability"],x["video_id"],x["start_ms"]))
    counts,seen,chosen={},set(),[]
    for x in admissible:
        key=(x["target"],x["video_id"])
        span=(key,x["start_ms"],x["end_ms"])
        if span in seen:
            rejected.append({"candidate_index":x["candidate_index"],"reason":"DUPLICATE_SPAN"})
            continue
        if counts.get(key,0)>=MAX_PER_TARGET_SOURCE:
            rejected.append({"candidate_index":x["candidate_index"],"reason":"REVIEW_CAP_PER_SOURCE"})
            continue
        seen.add(span)
        counts[key]=counts.get(key,0)+1
        chosen.append(x)
    chosen.sort(key=lambda x:(TARGETS.index(x["target"]),x["video_id"],x["start_ms"]))
    return chosen,rejected

def atomic_private_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix=".private-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
            f.write("\n");f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def clip_wav(media,item,path):
    if path.exists() or path.is_symlink():
        raise ReviewBlocked("CLIP_DESTINATION_ALREADY_EXISTS")
    start,end=item["clip_start_ms"],item["clip_end_ms"]
    command=[
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
        "-i",str(media),"-ss",f"{start/1000:.3f}",
        "-t",f"{(end-start)/1000:.3f}","-map","0:a:0","-vn",
        "-ac","1","-ar","16000","-c:a","pcm_s16le",str(path),
    ]
    try:
        run=subprocess.run(command,stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,timeout=80,check=False)
    except (OSError,subprocess.TimeoutExpired) as e:
        raise ReviewBlocked("PRIVATE_FFMPEG_CLIP_TIMEOUT_OR_UNAVAILABLE") from e
    if run.returncode or not path.is_file() or path.stat().st_size<1024:
        raise ReviewBlocked("PRIVATE_AUDIO_CLIP_FAILED")
    os.chmod(path,0o600)
    return digest(path)

def prepare(root):
    root=Path(root)
    evidence=root/"owner-voice-acoustic-execution/evidence"
    media=root/"owner-voice-dubbing-input"
    target=root/"owner-voice-acoustic-curation-v1"
    if any(x.is_symlink() for x in (evidence,media,target)):
        raise ReviewBlocked("UNTRUSTED_PRIVATE_SYMLINK")
    videos,named=validate_receipt(evidence)
    for vid in FILES:
        original=media/(vid+".mp4")
        if (original.is_symlink() or not original.is_file()
                or digest(original)!=FILES[vid]):
            raise ReviewBlocked("SOURCE_MEDIA_HASH_MISMATCH_"+vid)
    inputs={name:digest(evidence/name) for name in (
        "run-state.json","candidate-report.json","coverage-quality.json",
        "named-phrase-candidates.json"
    )}
    chosen,rejected=choose_candidates(videos,named)
    if target.exists():
        old=safe_json(target/"manifest.json")
        if old.get("evidence_sha256")!=inputs:
            raise ReviewBlocked("EXISTING_CURATION_HAS_DIFFERENT_SOURCE")
        clips=old.get("clips",[])
        for c in clips:
            # Do not permit paths from tampered manifests to escape review root.
            file=c.get("file")
            if (not isinstance(file,str)
                or not re.fullmatch(r"clips/[0-9]{2}-(f8IZhKcuEts|K6rVM6gn6k4)\.wav",file)):
                raise ReviewBlocked("EXISTING_CURATION_PATH_INVALID")
            clip=target/file
            if clip.is_symlink() or not clip.is_file() or digest(clip)!=c.get("clip_sha256"):
                raise ReviewBlocked("EXISTING_CURATION_CLIP_MISMATCH")
        return old,"REUSED_VERIFIED"
    with tempfile.TemporaryDirectory(prefix=".curation-",dir=root) as d:
        folder=Path(d)
        os.chmod(folder,0o700)
        (folder/"clips").mkdir(mode=0o700)
        clips=[]
        for i,item in enumerate(chosen):
            file=f"clips/{i+1:02d}-{item['video_id']}.wav"
            checksum=clip_wav(media/(item["video_id"]+".mp4"),item,folder/file)
            clips.append(item|{"file":file,"clip_sha256":checksum})
        manifest={
            "schema":"OwnerVoiceAcousticHumanCuration/v1",
            "status":"CLIPS_READY_HUMAN_REVIEW" if clips else "NO_SAFE_CLIPS",
            "evidence_sha256":inputs,
            "targets":{t:sum(x["target"]==t for x in clips) for t in TARGETS},
            "eligible_clip_count":len(clips),
            "rejected_candidate_count":len(rejected),
            "rejections":rejected,
            "clips":clips,
            "provenance":"TWO_EXISTING_DUBBED_VIDEOS_NOT_OWNER_SPEAKER",
            "speaker_reference_allowed":False,
            "phonetic_pronunciations_verified":0,
            "owner_voice_changed":False,
            "telegram_delivery":"NOT_ATTEMPTED",
            "youtube_delivery":"NOT_ATTEMPTED",
            "human_approval":"PENDING",
        }
        atomic_private_json(folder/"manifest.json",manifest)
        os.rename(folder,target)
    return manifest,"CREATED"

def main():
    if not (os.environ.get("CODESPACES")=="true"
            and os.environ.get("CODESPACE_NAME")==CODESPACE
            and os.environ.get("GITHUB_REPOSITORY")==REPO):
        raise ReviewBlocked("AUTHORIZATION_DENIED_EXISTING_CODESPACE_ONLY")
    home=Path.home()
    root=home/".local/share/br-no-gta"
    if not root.is_dir() or any(p.is_symlink() for p in (
        home,home/".local",home/".local/share",root
    )):
        raise ReviewBlocked("ORIGINAL_PRIVATE_ASR_ROOT_MISSING_OR_SYMLINK")
    lockfile=root/"owner-voice-acoustic-execution/.exclusive.lock"
    if lockfile.is_symlink() or not lockfile.is_file():
        raise ReviewBlocked("ASR_LOCK_MISSING_OR_UNTRUSTED")
    with lockfile.open("a+b") as f:
        try:
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise ReviewBlocked("ANOTHER_ASR_OR_CURATION_RUN_ACTIVE") from e
        manifest,mode=prepare(root)
    print("CURATION_RESULT="+manifest["status"],flush=True)
    print("CURATION_RUN="+mode,flush=True)
    for label in TARGETS:
        print("TARGET="+label.replace(" ","_")+
              " PRIVATE_CLIPS="+str(manifest["targets"][label]),flush=True)
    print("PRIVATE_CLIPS_TOTAL="+str(manifest["eligible_clip_count"]),flush=True)
    print("REJECTED_CANDIDATES="+str(manifest["rejected_candidate_count"]),flush=True)
    print("ACOUSTIC_REVIEW=PENDING",flush=True)
    print("SPEAKER_REFERENCE_ALLOWED=FALSE",flush=True)
    print("CURATION_PRIVATE_DIRECTORY="+str(root/"owner-voice-acoustic-curation-v1"),flush=True)
    return 0

if __name__=="__main__":
    try:
        sys.exit(main())
    except ReviewBlocked as err:
        # All messages are fixed error codes generated within this script.
        print("PRIVATE_ACOUSTIC_REVIEW=FAIL "+str(err)[:120],file=sys.stderr)
        sys.exit(2)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        print("PRIVATE_ACOUSTIC_REVIEW=FAIL SANITIZED_UNEXPECTED_ERROR",file=sys.stderr)
        sys.exit(2)
