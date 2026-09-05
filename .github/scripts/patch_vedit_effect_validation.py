from pathlib import Path

p = Path("backend/vedit/store.py")
s = p.read_text()

old = """    def add_effect(self, clip_id: str | None, effect: str, params: dict | None = None) -> Effect:
        \"\"\"clip_id=None applica l'effetto al master.\"\"\"
        clean = fx.validate_effect(effect, params or {})
        target = self.project.master.effects if clip_id is None else self.clip_for_edit(clip_id)[1].effects
"""

new = """    def add_effect(self, clip_id: str | None, effect: str, params: dict | None = None) -> Effect:
        \"\"\"clip_id=None applica l'effetto al master.\"\"\"
        try:
            clean = fx.validate_effect(effect, params or {})
        except ValueError as exc:
            raise EditError(str(exc)) from exc

        target = self.project.master.effects if clip_id is None else self.clip_for_edit(clip_id)[1].effects
"""

if old not in s:
    raise SystemExit(
        "ERRO: bloco Store.add_effect esperado não encontrado."
    )

if "except (ValueError, KeyError) as exc:" in s:
    raise SystemExit(
        "ERRO: patch de validação de efeitos já aplicado."
    )

s = s.replace(old, new, 1)

p.write_text(s)

print("===== VEDIT EFFECT VALIDATION PATCH =====")
print("Erros de validação de efeitos -> EditError.")
print("Somente ValueError vindo de validate_effect é convertido.")
print("Exceções fora dessa fronteira continuam inesperadas.")
print("===== END VEDIT EFFECT VALIDATION PATCH =====")
