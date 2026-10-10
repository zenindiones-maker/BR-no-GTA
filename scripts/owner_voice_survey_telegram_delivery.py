#!/usr/bin/env python3
"""Fail-closed, one-album listening review for six pre-existing private survey WAVs.

The source speakers are NOT BR_OWNER_V1. No ASR, voice conditioning, local A15
audio, public media, automatic retries, or unattended delivery. The only
external side effect is ONE explicitly requested protected sendMediaGroup.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import urllib.parse
import urllib.request
import wave

CODESPACE="br-v23-recovery-gxp67g5g7wphwxjw"
REPOSITORY="zenindiones-maker/BR-no-GTA"
FILES={
    "f8IZhKcuEts":"b4e981094e468a2ca5f5d270ff2a5338187df935a8d177971a2640bcc28f34be",
    "K6rVM6gn6k4":"ec4645c92e41be73a077f33f04159e45b9abc35c7843d5c7a35be7ccd75a1e52",
}
CLIP_NAME=re.compile(r"clips/(0[1-6])-(f8IZhKcuEts|K6rVM6gn6k4)\.wav\Z")
CHECKSUM=re.compile(r"[a-f0-9]{64}\Z")
RECEIPT="telegram-delivery-v1.json"

class ReviewBlocked(RuntimeError):
    pass

def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def read_json(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():
        raise ReviewBlocked("UNTRUSTED_OR_MISSING_PRIVATE_RECEIPT")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream,parse_constant=lambda _:(_ for _ in ()).throw(
            ReviewBlocked("NONFINITE_PRIVATE_RECEIPT")
        ))

def atomic_json(path,payload):
    path=Path(path)
    if path.is_symlink():
        raise ReviewBlocked("SYMLINK_RECEIPT_FORBIDDEN")
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temp=tempfile.mkstemp(dir=str(path.parent),prefix=".private-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(payload,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp,0o600)
        os.replace(temp,path)
        dirfd=os.open(str(path.parent),os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def validate_bundle(folder):
    """Prove every byte comes from six immutable, survey-only source clips."""
    folder=Path(folder)
    if folder.is_symlink() or (folder/"clips").is_symlink():
        raise ReviewBlocked("SYMLINK_PRIVATE_BUNDLE_FORBIDDEN")
    manifest=read_json(folder/"manifest.json")
    if not isinstance(manifest,dict):
        raise ReviewBlocked("INVALID_CURATED_MANIFEST")
    if not (
        manifest.get("schema")=="OwnerVoiceAcousticHumanCuration/v2"
        and manifest.get("status")=="SEGMENT_SURVEY_READY_HUMAN_REVIEW"
        and manifest.get("provenance")=="TWO_EXISTING_DUBBED_VIDEOS_NOT_OWNER_SPEAKER"
        and manifest.get("named_input_candidate_count")==0
        and manifest.get("named_target_clip_count")==0
        and manifest.get("survey_clip_count")==6
        and manifest.get("eligible_clip_count")==6
        and manifest.get("phonetic_pronunciations_verified")==0
        and manifest.get("speaker_reference_allowed") is False
        and manifest.get("owner_voice_changed") is False
        and manifest.get("human_approval")=="PENDING"
        and manifest.get("telegram_delivery")=="NOT_ATTEMPTED"
        and isinstance(manifest.get("evidence_sha256"),dict)
        and manifest["evidence_sha256"]
        and all(isinstance(k,str) and CHECKSUM.fullmatch(v or "")
                for k,v in manifest["evidence_sha256"].items())
    ):
        raise ReviewBlocked("UNTRUSTED_OR_INELIGIBLE_CURATION")
    items=manifest.get("clips")
    if not isinstance(items,list) or len(items)!=6:
        raise ReviewBlocked("EXACT_SIX_SURVEY_CLIPS_REQUIRED")
    verified=[]
    seen=set()
    counts={vid:0 for vid in FILES}
    for item in items:
        if not isinstance(item,dict):
            raise ReviewBlocked("INVALID_CLIP_DESCRIPTOR")
        rel=item.get("file")
        if not isinstance(rel,str):
            raise ReviewBlocked("INVALID_CLIP_PATH")
        match=CLIP_NAME.fullmatch(rel)
        if match is None or rel in seen:
            raise ReviewBlocked("INVALID_OR_DUPLICATE_CLIP_PATH")
        seen.add(rel)
        video_id=match.group(2)
        if item.get("video_id")!=video_id or item.get("media_sha256")!=FILES[video_id]:
            raise ReviewBlocked("ORIGINAL_MEDIA_PROVENANCE_MISMATCH")
        if item.get("source_speaker_identity")!="NOT_BR_OWNER_V1":
            raise ReviewBlocked("OWNER_IDENTITY_CONFLATION_FORBIDDEN")
        if not (
            item.get("target") is None
            and item.get("evidence_class")=="SEGMENT_SURVEY_NOT_NAMED_PRONUNCIATION"
            and item.get("speaker_reference_allowed") is False
            and item.get("human_approval")=="PENDING"
            and item.get("acoustic_review")=="PENDING"
        ):
            raise ReviewBlocked("FALSE_PRONUNCIATION_OR_APPROVAL_CLAIM")
        wav=folder/rel
        if wav.is_symlink():
            raise ReviewBlocked("SYMLINK_CLIP_FORBIDDEN")
        if not wav.is_file() or not 1024<=wav.stat().st_size<=1500000:
            raise ReviewBlocked("CLIP_FILE_UNAVAILABLE_OR_TOO_LARGE")
        if not CHECKSUM.fullmatch(str(item.get("clip_sha256") or "")):
            raise ReviewBlocked("CLIP_HASH_INVALID")
        if digest(wav)!=item["clip_sha256"]:
            raise ReviewBlocked("CLIP_HASH_MISMATCH")
        try:
            with wave.open(str(wav),"rb") as audio:
                valid=(audio.getnchannels()==1 and audio.getsampwidth()==2
                       and audio.getframerate()==16000
                       and 1<=audio.getnframes()<=16000*6)
        except (OSError,EOFError,wave.Error):
            valid=False
        if not valid:
            raise ReviewBlocked("CLIP_PCM_FORMAT_INVALID")
        counts[video_id]+=1
        verified.append({"file":rel,"video_id":video_id,"bytes":wav.stat().st_size,
                         "clip_sha256":item["clip_sha256"]})
    if sorted(counts.values())!=[3,3]:
        raise ReviewBlocked("SURVEY_SOURCE_COVERAGE_MISMATCH")
    return {"folder":folder,"digest":digest(folder/"manifest.json"),"clips":verified}

def prepare_album(bundle,chat_id):
    """One Telegram sendMediaGroup of six original, hash-checked WAV documents."""
    media=[]
    for i,item in enumerate(bundle["clips"],start=1):
        label="YouDubbing" if item["video_id"]=="f8IZhKcuEts" else "MANGÁ K"
        media.append({
            "type":"document",
            "media":f"attach://clip_{i}",
            "caption":(
                f"BR no GTA · Escuta exploratória {i}/6 · {label}\n"
                "Áudio de vídeo dublado, NÃO é voz BR_OWNER_V1; "
                "NÃO é prova de pronúncia. Avaliação humana pendente."
            ),
        })
    fields={"chat_id":str(chat_id),"media":json.dumps(media,ensure_ascii=False),
            "protect_content":"true"}
    return media,fields

def validate_telegram_chat(bot,chat,expected_id=None):
    if str(bot.get("username") or "").casefold()!="brnogta_bot":
        raise ReviewBlocked("WRONG_BOT_IDENTITY")
    if chat.get("type") not in ("group","supergroup"):
        raise ReviewBlocked("REVIEW_DESTINATION_NOT_GROUP")
    if chat.get("username"):
        raise ReviewBlocked("PUBLIC_REVIEW_DESTINATION_FORBIDDEN")
    cid=chat.get("id")
    if type(cid) is not int or cid>=0:
        raise ReviewBlocked("INVALID_TELEGRAM_CHAT_ID")
    if expected_id is not None and cid!=expected_id:
        raise ReviewBlocked("TELEGRAM_CHAT_ID_MISMATCH")
    return cid

def telegram_call(method,token,fields=None,files=None):
    """STD-LIB-only Telegram Bot API client. Never print credentials/HTTP error."""
    if method not in ("getMe","getChat","sendMediaGroup"):
        raise ReviewBlocked("TELEGRAM_METHOD_FORBIDDEN")
    fields=dict(fields or {})
    url="https://api.telegram.org/bot"+token+"/"+method
    if files:
        boundary="BRVoiceSurvey"+secrets.token_hex(16)
        chunks=[]
        for name,value in fields.items():
            chunks.append(("--"+boundary+"\r\nContent-Disposition: form-data; name=\""+
                           name+"\"\r\n\r\n"+str(value)+"\r\n").encode())
        for key,content in files.items():
            safe_name=f"BR_no_GTA_survey_{key}.wav"
            chunks.append(("--"+boundary+"\r\nContent-Disposition: form-data; name=\""+
                           key+"\"; filename=\""+safe_name+"\"\r\n"
                           "Content-Type: audio/wav\r\n\r\n").encode()+content+b"\r\n")
        chunks.append(("--"+boundary+"--\r\n").encode())
        data=b"".join(chunks)
        ctype="multipart/form-data; boundary="+boundary
    else:
        data=urllib.parse.urlencode(fields).encode()
        ctype="application/x-www-form-urlencoded"
    req=urllib.request.Request(url,data=data,method="POST",
                               headers={"Content-Type":ctype})
    with urllib.request.urlopen(req,timeout=90) as response:
        obj=json.loads(response.read().decode("utf-8"))
    if not isinstance(obj,dict) or obj.get("ok") is not True:
        raise ReviewBlocked("TELEGRAM_API_NOT_OK")
    return obj.get("result")

def _state_path(folder):
    return Path(folder)/RECEIPT

def _reconcile_existing(folder,bundle,chat_id):
    state_path=_state_path(folder)
    if not state_path.exists():
        return None
    state=read_json(state_path)
    if not isinstance(state,dict) or state.get("schema")!="OwnerVoiceSurveyTelegramDelivery/v1":
        raise ReviewBlocked("DELIVERY_LEDGER_INVALID")
    if (state.get("manifest_sha256")!=bundle["digest"]
            or state.get("chat_id")!=chat_id
            or state.get("clip_sha256")!=[c["clip_sha256"] for c in bundle["clips"]]):
        raise ReviewBlocked("DELIVERY_BINDING_MISMATCH")
    if state.get("state")=="CONFIRMED":
        if len(state.get("message_ids",[]))!=6:
            raise ReviewBlocked("DELIVERY_LEDGER_INCOMPLETE")
        return {"state":"CONFIRMED","message_count":6,"reused":True}
    raise ReviewBlocked("RECONCILIATION_REQUIRED_NO_BLIND_TELEGRAM_RETRY")

def _send_album(bundle,token,chat_id):
    """SENDING-before-side-effect persisted; POST uncertainty cannot auto-retry."""
    ledger=_state_path(bundle["folder"])
    pending={
        "schema":"OwnerVoiceSurveyTelegramDelivery/v1",
        "manifest_sha256":bundle["digest"],
        "clip_sha256":[c["clip_sha256"] for c in bundle["clips"]],
        "chat_id":chat_id,
        "state":"SENDING",
        "attempt_count":1,
        "message_ids":[],
        "human_review":"PENDING",
        "pronunciation_verified":False,
        "owner_voice_changed":False,
    }
    atomic_json(ledger,pending)
    _,fields=prepare_album(bundle,chat_id)
    try:
        data={
            "clip_"+str(i): (bundle["folder"]/clip["file"]).read_bytes()
            for i,clip in enumerate(bundle["clips"],start=1)
        }
        messages=telegram_call("sendMediaGroup",token,fields,data)
        if (not isinstance(messages,list) or len(messages)!=6
                or any(not isinstance(x,dict) for x in messages)):
            raise ValueError("INCOMPLETE_ALBUM_RECEIPT")
        ids=[msg.get("message_id") for msg in messages]
        album_ids=[msg.get("media_group_id") for msg in messages]
        if (any(type(n) is not int or n<=0 for n in ids)
                or len(set(ids))!=6
                or not album_ids[0] or len(set(album_ids))!=1
                or any((msg.get("chat") or {}).get("id")!=chat_id for msg in messages)):
            raise ValueError("ALBUM_RECEIPT_PROVENANCE_FAILED")
        done=dict(pending,state="CONFIRMED",message_ids=ids)
        atomic_json(ledger,done)
        return {"state":"CONFIRMED","message_count":6,"reused":False}
    except Exception:
        # An HTTP failure after a POST may have reached Telegram. NEVER repeat.
        unknown=dict(pending,state="UNKNOWN_REMOTE_STATE",
                     reconciliation_required=True)
        atomic_json(ledger,unknown)
        raise ReviewBlocked("UNKNOWN_REMOTE_STATE_MANUAL_RECONCILIATION_REQUIRED") from None

def execute(folder,mode="preflight"):
    if mode not in ("preflight","verify-target","send"):
        raise ReviewBlocked("INVALID_REVIEW_ACTION")
    bundle=validate_bundle(folder)
    token=os.environ.get("TELEGRAM_BOT_TOKEN","").strip()
    chat=os.environ.get("TELEGRAM_REVIEW_CHAT_ID","").strip()
    configured=bool(token and re.fullmatch(r"-[0-9]{2,20}",chat))
    if mode=="preflight":
        return {"state":"PREPARED","review_clips":len(bundle["clips"]),
                "telegram_credentials":"PRESENT" if configured else "MISSING",
                "no_audio_sent":True}
    if not configured:
        raise ReviewBlocked("TELEGRAM_CREDENTIALS_MISSING_IN_EXISTING_CODESPACE")
    cid=int(chat)
    if mode=="verify-target":
        bot=telegram_call("getMe",token)
        target=telegram_call("getChat",token,{"chat_id":chat})
        validate_telegram_chat(bot,target,expected_id=cid)
        return {"state":"TARGET_VERIFIED","review_clips":len(bundle["clips"]),
                "telegram_credentials":"PRESENT","no_audio_sent":True}
    lock_path=Path(folder)/".telegram-send.lock"
    if lock_path.is_symlink():
        raise ReviewBlocked("TELEGRAM_LOCK_SYMLINK_FORBIDDEN")
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReviewBlocked("TELEGRAM_SEND_ALREADY_ACTIVE") from None
        old=_reconcile_existing(folder,bundle,cid)
        if old is not None:
            return old
        # No outbound upload before verifying the authenticated bot and the
        # private group with read-only Telegram methods.
        bot=telegram_call("getMe",token)
        target=telegram_call("getChat",token,{"chat_id":chat})
        validate_telegram_chat(bot,target,expected_id=cid)
        return _send_album(bundle,token,cid)

def main(argv=None):
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--preflight",action="store_true")
    group.add_argument("--verify-target",action="store_true")
    group.add_argument("--send",action="store_true")
    args=parser.parse_args(argv)
    # Identity BEFORE inspecting private media or external network.
    if not (os.environ.get("CODESPACES")=="true"
            and os.environ.get("CODESPACE_NAME")==CODESPACE
            and os.environ.get("GITHUB_REPOSITORY")==REPOSITORY):
        raise ReviewBlocked("AUTHORIZATION_DENIED_EXISTING_CODESPACE_ONLY")
    folder=Path.home()/".local/share/br-no-gta/owner-voice-acoustic-curation-v2"
    result=execute(folder,mode="send" if args.send else
                   "verify-target" if args.verify_target else "preflight")
    print("SURVEY_TELEGRAM_DELIVERY="+result["state"],flush=True)
    if "telegram_credentials" in result:
        print("TELEGRAM_REMOTE_CREDENTIALS="+result["telegram_credentials"],flush=True)
    if "message_count" in result:
        print("TELEGRAM_REVIEW_AUDIO_MESSAGES="+str(result["message_count"]),flush=True)
    print("ACOUSTIC_REVIEW=PENDING",flush=True)
    print("BR_OWNER_V1_ACTIVATION=FORBIDDEN",flush=True)
    return 0

if __name__=="__main__":
    try:
        sys.exit(main())
    except ReviewBlocked as err:
        print("SURVEY_TELEGRAM_DELIVERY=BLOCKED "+str(err)[:160],file=sys.stderr)
        sys.exit(2)
    except Exception:
        print("SURVEY_TELEGRAM_DELIVERY=BLOCKED SANITIZED_UNEXPECTED_ERROR",
              file=sys.stderr)
        sys.exit(2)
