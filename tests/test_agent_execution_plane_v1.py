from scripts.agent_execution_plane_canary import main

def test_execution_plane_canary(capsys):
 main();out=capsys.readouterr().out
 for gate in ("TASK_REQUIREMENT_DRIVES_SELECTION=PASS","HARD_ELIGIBILITY_BEFORE_RANKING=PASS","NO_AGENT_NAME_ROUTING=PASS","NO_TASK_ID_ROUTING=PASS","TASK_EXECUTION_ENVELOPE_LIVE=PASS","TASK_EXECUTION_EVIDENCE_LIVE=PASS","WORKER_AUTHORITY_ESCALATION=0"):assert gate in out
