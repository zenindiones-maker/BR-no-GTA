"""Real CPU ONNX compact encoder, SHADOW ONLY: no tool routing or permissions.

Exact HF revision and model SHA256, no pickle, transformers remote code,
paid service, user voice, automatic promotion or self-training.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO="sentence-transformers/paraphrase-MiniLM-L3-v2"
REVISION="4056ec5a34457110fd02a60216d646e012dbd988"
MODEL_SHA256="84007b609c7a626b0adf825b1e36b839e705cd5995b4865b6e6696541d0a6350"
LICENSE="apache-2.0"
STATUS="SHADOW_EXPERIMENT_ONLY"
MAX_LENGTH=320
TEMPLATE={
    "visual":(
        "Inspect cuts and scene changes in an authorized local MP4 video using FFmpeg",
        "Analyze timeline and visual transition in owner-created video frames",
        "Verificar mudanças de cena e cortes em um vídeo próprio com FFmpeg",
        "Inspecionar quadros e transições de vídeo sem publicar",
    ),
    "ledger":(
        "Inspect a private Telegram delivery ledger and reconcile failed message delivery",
        "Check delivery receipts and remote commit references without writing or resending",
        "Conferir o ledger privado de entregas Telegram sem reenviar mensagens",
        "Auditar confirmação da entrega de dublagem e estado do ledger de voz",
    ),
}
_DENY=re.compile(
    r"(?i)\b(ignore (?:all )?(?:previous )?instructions|override (?:policy|authorization)|"
    r"expose (?:secret|token|password)|send (?:me )?(?:the )?(?:key|credentials)|"
    r"publique|publicar|publish|upload|force.push|enviar (?:a |para )?voz|"
    r"train(?:ing)?|fine.tune|finetune)\b"
)


def _sha(path:Path)->str:
    d=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            d.update(block)
    return d.hexdigest()


def fetch_pinned_files(*,destination:Path)->dict[str,Any]:
    if not destination.is_absolute() or not destination.is_dir() or destination.is_symlink():
        raise ValueError("SLM_SHADOW_PRIVATE_MODEL_DESTINATION_INVALID")
    from huggingface_hub import hf_hub_download
    paths={}
    for name in ("onnx/model.onnx","tokenizer.json"):
        p=Path(hf_hub_download(
            repo_id=REPO,filename=name,revision=REVISION,local_dir=destination,
            local_dir_use_symlinks=False,
        ))
        if not p.is_file() or p.is_symlink():
            raise RuntimeError("SLM_SHADOW_PINNED_MODEL_MISSING")
        paths[name]=p
    digest=_sha(paths["onnx/model.onnx"])
    if digest!=MODEL_SHA256:
        raise RuntimeError("SLM_SHADOW_MODEL_SHA256_MISMATCH")
    return {
        "repository":REPO,"revision":REVISION,"license":LICENSE,
        "onnx_sha256":digest,"tokenizer_sha256":_sha(paths["tokenizer.json"]),
        "onnx_bytes":paths["onnx/model.onnx"].stat().st_size,
        "downloaded_in_ephemeral_job_only":True,
        "paid_provider_used":False,
        "remote_code_executed":False,
    }


class OnnxMiniEncoder:
    def __init__(self,model_dir:Path):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        model=model_dir/"onnx"/"model.onnx"
        tok_file=model_dir/"tokenizer.json"
        if _sha(model)!=MODEL_SHA256:
            raise RuntimeError("SLM_SHADOW_UNVERIFIED_MODEL_BYTES")
        self.tokenizer=Tokenizer.from_file(str(tok_file))
        self.tokenizer.enable_truncation(max_length=128)
        self.tokenizer.enable_padding(pad_id=0,pad_token="[PAD]")
        opts=ort.SessionOptions()
        opts.intra_op_num_threads=2
        opts.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(model),sess_options=opts,providers=["CPUExecutionProvider"])
        names={x.name for x in self.session.get_inputs()}
        if not names.issubset({"input_ids","attention_mask","token_type_ids"}) or not {"input_ids","attention_mask"}.issubset(names):
            raise RuntimeError("SLM_SHADOW_ONNX_INPUT_SCHEMA_UNEXPECTED")
        self.input_names=names

    def encode(self,texts:list[str]):
        import numpy as np
        if not isinstance(texts,list) or not texts or len(texts)>64 or any(
            not isinstance(v,str) or not 1<=len(v)<=MAX_LENGTH for v in texts
        ):
            raise ValueError("SLM_SHADOW_TEXT_BOUNDS_INVALID")
        encoded=self.tokenizer.encode_batch(texts)
        feeds={
            "input_ids":np.array([x.ids for x in encoded],dtype=np.int64),
            "attention_mask":np.array([x.attention_mask for x in encoded],dtype=np.int64),
            "token_type_ids":np.array([x.type_ids for x in encoded],dtype=np.int64),
        }
        result=self.session.run(None,{k:feeds[k] for k in self.input_names})
        if not result:
            raise RuntimeError("SLM_SHADOW_ONNX_EMPTY_OUTPUT")
        hidden=np.asarray(result[0],dtype=np.float32)
        if hidden.ndim!=3 or hidden.shape[0]!=len(texts) or hidden.shape[2]!=384:
            raise RuntimeError("SLM_SHADOW_EMBEDDING_DIMENSIONS_INVALID")
        mask=feeds["attention_mask"].astype(np.float32)[...,None]
        mean=(hidden*mask).sum(axis=1)/np.maximum(mask.sum(axis=1),1.0)
        norm=np.linalg.norm(mean,axis=1,keepdims=True)
        if not np.isfinite(norm).all() or np.any(norm<1e-8):
            raise RuntimeError("SLM_SHADOW_NONFINITE_EMBEDDINGS")
        return mean/np.maximum(norm,1e-8)


@dataclass(frozen=True)
class ShadowPolicy:
    min_similarity:float=0.48
    min_margin:float=0.05
    max_request_length:int=MAX_LENGTH
    no_execution:bool=True


def shadow_suggest(*,encoder:OnnxMiniEncoder,text:str,policy:ShadowPolicy=ShadowPolicy())->dict:
    """Model proposes domain only; independent Harness selector is not invoked."""
    if not isinstance(text,str) or not 1<=len(text)<=policy.max_request_length:
        raise ValueError("SLM_SHADOW_REQUEST_INVALID")
    if _DENY.search(text):
        return {
            "status":"ABSTAIN","suggested_domain":None,
            "reason":"PROTECTED_OR_CONSEQUENTIAL_REQUEST",
            "confidence":None,"margin":None,
            "model_executed":False,
            "harness_tool_invoked":False,"remote_ledger_read":False,
            "can_authorize":False,"publish_authorized":False,
        }
    import numpy as np
    prompts=[text,*TEMPLATE["visual"],*TEMPLATE["ledger"]]
    embeddings=encoder.encode(prompts)
    query=embeddings[0]
    k=len(TEMPLATE["visual"])
    scores={
        "visual":float(np.max(embeddings[1:1+k]@query)),
        "ledger":float(np.max(embeddings[1+k:]@query)),
    }
    ranked=sorted(scores.items(),key=lambda item:item[1],reverse=True)
    top,runner_up=ranked[0],ranked[1]
    margin=top[1]-runner_up[1]
    accepted=top[1]>=policy.min_similarity and margin>=policy.min_margin
    return {
        "status":"PROPOSAL_ONLY" if accepted else "ABSTAIN",
        "suggested_domain":top[0] if accepted else None,
        "reason":"SHADOW_SEMANTIC_SIMILARITY" if accepted else "INSUFFICIENT_EVIDENCE",
        "confidence":round(top[1],5),"margin":round(margin,5),
        "model_executed":True,"model_family":REPO,
        "harness_tool_invoked":False,
        "remote_ledger_read":False,
        "can_authorize":False,"publish_authorized":False,
    }
