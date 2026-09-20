from app.services.video_a_script_quality import validate_script_quality

def _evidence(n=24):
    return [
        {"FINDING_ID":f"EL{i:03d}","EDITORIAL_VALUE":"HIGH" if i<=15 else "MEDIUM"}
        for i in range(1,n+1)
    ]

def test_rejects_production_metadata_even_when_supported():
    package={
        "EDITORIAL_NOVELTY":"PASS",
        "central_question":"O que mudou?",
        "answer_thesis":"O vídeo mostra sistemas concretos.",
        "evidence_map":_evidence(),
        "script":{"sections":[
            {
                "section_id":"H","role":"hook",
                "narration":"Booooa meu povo, aqui é BR no GTA 6 e hoje vamos descobrir três mudanças concretas que alteram como o jogo funciona de verdade.",
                "evidence_ids":["EL001","EL002"],
                "audience_value":"Promessa concreta."
            },
            *[
                {
                    "section_id":f"S{i}","role":"body",
                    "narration":("O vídeo rejeitado e o sistema de produção não pertencem ao espectador. "
                                 "Esta seção contém fatos concretos observados no material oficial e explica por que eles mudam a experiência. ")*8,
                    "evidence_ids":[f"EL{j:03d}" for j in range(1,24)],
                    "audience_value":"Entrega informação."
                } for i in range(1,9)
            ]
        ]}
    }
    result=validate_script_quality(package)
    assert result["META_PRODUCTION_LEAKAGE"]>0
    assert result["SCRIPT_EDITORIAL_QUALITY"]=="FAIL"

def test_unsupported_evidence_is_fail_closed():
    package={
        "EDITORIAL_NOVELTY":"PASS",
        "central_question":"Q","answer_thesis":"A",
        "evidence_map":_evidence(),
        "script":{"sections":[{
            "section_id":"H","role":"hook",
            "narration":"Booooa meu povo, aqui é BR no GTA 6 e hoje vamos ver o que realmente mudou e por que isso importa para quem vai jogar.",
            "evidence_ids":["MISSING"],
            "audience_value":"Valor."
        }]}
    }
    result=validate_script_quality(package)
    assert result["UNSUPPORTED_CLAIMS"]==1
    assert result["FACTUAL_SUPPORT"]=="FAIL"
