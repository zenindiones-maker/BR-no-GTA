from pathlib import Path


p = Path("backend/vedit/story.py")
lines = p.read_text().splitlines(keepends=True)

matches = [
    i
    for i, line in enumerate(lines)
    if 'out.append(f"durata {total:.1f}s contro {target:.1f}s richiesti: "' in line
]

if len(matches) != 1:
    raise SystemExit(
        f"Expected exactly one Vedit timing line, found {len(matches)}."
    )

i = matches[0]

if i + 1 >= len(lines):
    raise SystemExit("ERRO: continuação da expressão Vedit não encontrada.")

if "si puo\\' stringere ancora" not in lines[i + 1]:
    raise SystemExit(
        "ERRO: continuação da expressão Vedit não corresponde ao código esperado."
    )

indent = lines[i].split("out.append", 1)[0]

lines[i:i + 2] = [
    indent + "out.append(\n",
    indent + '    f"durata {total:.1f}s contro {target:.1f}s richiesti: "\n',
    indent + '    + ("serve altro materiale" if total < target else "si puo" + chr(39) + " stringere ancora")\n',
    indent + ")\n",
]

p.write_text("".join(lines))

print("===== VEDIT PATCH =====")
print("Python 3.11 syntax compatibility patch applied.")
print("===== END VEDIT PATCH =====")
