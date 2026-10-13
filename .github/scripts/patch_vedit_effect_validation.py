from pathlib import Path


p = Path("backend/vedit/store.py")
s = p.read_text()

already = """        try:
            clean = fx.validate_effect(effect, params or {})
        except ValueError as exc:
            raise EditError(str(exc)) from exc
"""

if already in s:
    print("===== VEDIT EFFECT VALIDATION PATCH =====")
    print("Patch ja aplicado em Store.add_effect.")
    print("===== END VEDIT EFFECT VALIDATION PATCH =====")
    raise SystemExit(0)

old = "        clean = fx.validate_effect(effect, params or {})\n"
new = already

if s.count(old) != 1:
    raise SystemExit(
        "ERRO: linha Store.add_effect esperada nao encontrada "
        f"({s.count(old)} ocorrencias)."
    )

if "class EditError" not in s:
    raise SystemExit("ERRO: EditError nao existe em store.py.")

p.write_text(s.replace(old, new, 1))

print("===== VEDIT EFFECT VALIDATION PATCH =====")
print("Erros de validacao de efeitos -> EditError.")
print("Somente ValueError vindo de validate_effect e convertido.")
print("KeyError continua KeyError. Excecoes fora dessa fronteira continuam inesperadas.")
print("===== END VEDIT EFFECT VALIDATION PATCH =====")
