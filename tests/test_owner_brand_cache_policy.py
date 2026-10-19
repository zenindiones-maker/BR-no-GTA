"""O check brand_audio_cache_policy virou falha permanente após o owner-only
(78548177): closing_fixed_reusable passou a ser False por política, mas o check
continuava exigindo True. O check agora valida a política do dono (fechamento
regenerado, invalidação por identidade/versão), em vez de exigir a Voice B fixa."""
from __future__ import annotations

import copy

from app.services.channel_spoken_branding_service import (
    brand_cache_policy_ok,
    build_spoken_branding_contract,
)


def test_owner_contract_cache_policy_passes():
    assert brand_cache_policy_ok(build_spoken_branding_contract(theme="teste")) is True


def test_reusable_fixed_closing_or_missing_identity_invalidation_fails():
    base = build_spoken_branding_contract(theme="teste")
    reusable = copy.deepcopy(base)
    reusable["cache_policy"]["closing_fixed_reusable"] = True
    assert brand_cache_policy_ok(reusable) is False
    no_identity = copy.deepcopy(base)
    no_identity["cache_policy"]["closing_invalidates_on"] = ["direction"]
    assert brand_cache_policy_ok(no_identity) is False
    no_lexicon = copy.deepcopy(base)
    no_lexicon["cache_policy"]["fingerprint_components"].remove("lexicon_version")
    assert brand_cache_policy_ok(no_lexicon) is False
    assert brand_cache_policy_ok({}) is False


def test_workers_use_owner_cache_policy_check():
    from pathlib import Path
    for path in ("app/workers/brand_asset_worker.py", "app/workers/professional_audiovisual_worker.py"):
        body = Path(path).read_text(encoding="utf-8")
        assert '"brand_audio_cache_policy": brand_cache_policy_ok(' in body
        assert 'bool(brand_contract["cache_policy"]["closing_fixed_reusable"])' not in body
        assert 'bool(spoken_branding["cache_policy"]["closing_fixed_reusable"])' not in body
