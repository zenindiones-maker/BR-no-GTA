#!/data/data/com.termux/files/usr/bin/bash

set -u

DEST="$HOME/GTA/BR"
SRC="$HOME/br-no-gta"
RELATORIO="$DEST/logs/consolidacao_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$DEST/logs"

{
    echo "============================================================"
    echo " BR NO GTA — CONSOLIDAÇÃO SEGURA"
    echo "============================================================"
    echo "ORIGEM : $SRC"
    echo "DESTINO: $DEST"
    echo "DATA   : $(date)"
    echo
    echo "REGRA: NENHUM ARQUIVO SERÁ APAGADO."
    echo "REGRA: CONFLITOS NÃO SERÃO SOBRESCRITOS."
    echo

    if [ ! -d "$SRC" ]; then
        echo "[ERRO] Origem não existe: $SRC"
        exit 1
    fi

    echo "=== ARQUIVOS NOVOS ==="

    find "$SRC" -type f \
        ! -path "$SRC/.venv/*" \
        ! -path "$SRC/.git/*" \
        -print0 |
    while IFS= read -r -d '' arquivo; do

        relativo="${arquivo#$SRC/}"
        destino="$DEST/$relativo"

        if [ ! -e "$destino" ]; then
            mkdir -p "$(dirname "$destino")"
            cp -p "$arquivo" "$destino"
            echo "[COPIADO] $relativo"
        fi
    done

    echo
    echo "=== CONFLITOS ==="

    find "$SRC" -type f \
        ! -path "$SRC/.venv/*" \
        ! -path "$SRC/.git/*" \
        -print0 |
    while IFS= read -r -d '' arquivo; do

        relativo="${arquivo#$SRC/}"
        destino="$DEST/$relativo"

        if [ -f "$destino" ]; then

            if ! cmp -s "$arquivo" "$destino"; then
                echo "[CONFLITO] $relativo"
                echo "  ORIGEM : $arquivo"
                echo "  DESTINO: $destino"
                echo "  -> NÃO SOBRESCRITO"
                echo
            fi

        fi
    done

    echo
    echo "=== ARQUIVOS AGORA PRESENTES NO PROJETO ÚNICO ==="

    find "$DEST" -type f \
        ! -path "$DEST/.venv/*" \
        ! -path "$DEST/.git/*" \
        -print | sort

    echo
    echo "============================================================"
    echo " CONSOLIDAÇÃO SEGURA CONCLUÍDA"
    echo "============================================================"
    echo "Relatório: $RELATORIO"

} | tee "$RELATORIO"
