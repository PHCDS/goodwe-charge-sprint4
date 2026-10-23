"""
GoodWe Charge - Sprint 4
Calculo de impacto a partir do historico de sessoes.

Le o dados/sessoes.csv gerado pelo despachante e responde tres perguntas:
quanto de CO2 deixou de sair porque a energia veio do sol e da bateria, quanto
de CO2 o carro eletrico evita em relacao a um carro a gasolina, e quanto o
operador economizou em reais.

Rodar: python scripts/impacto.py
"""

import csv
import os
import sys

ARQUIVO_CSV = "dados/sessoes.csv"
SAIDA = "docs/impacto.md"

# --- premissas, todas com fonte declarada ---

# Fator medio de emissao do SIN, publicado mensalmente pelo MCTI no SIRENE.
# Abril de 2025: 28,9 kg CO2/MWh. Trocar pelo mes da medicao de voces.
FATOR_SIN_KG_POR_KWH = 0.0289

# Carro a gasolina: 2,3 kg de CO2 por litro queimado, consumo de 10 km/l.
CO2_GASOLINA_KG_POR_LITRO = 2.3
CONSUMO_GASOLINA_KM_POR_LITRO = 10.0

# Carro eletrico: 5,5 km por kWh, media de um hatch compacto.
EFICIENCIA_EV_KM_POR_KWH = 5.5

# Tarifa residencial de São Paulo, com bandeira. Ajustar pela conta real.
TARIFA_FORA_PONTA = 0.85   # R$/kWh
TARIFA_PONTA = 1.25        # R$/kWh

# Projecao para a estacao em operacao. A demonstracao dura poucos minutos, entao
# os numeros medidos sao pequenos. Aqui a participacao renovavel medida e
# aplicada ao volume de uma estacao de verdade.
VAGAS = 6
SESSOES_POR_VAGA_DIA = 4
KWH_POR_SESSAO = 25        # recarga tipica de reforco, nao de 0 a 100%
DIAS_POR_ANO = 365


def ler_csv(caminho):
    if not os.path.exists(caminho):
        print(f"Nao encontrei {caminho}.")
        print("Rode o despachante primeiro: python scripts/despachante.py")
        sys.exit(1)
    with open(caminho, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ultima_linha_valida(linhas):
    """O CSV e cumulativo, entao o total da sessao esta na ultima linha."""
    for linha in reversed(linhas):
        if linha.get("kwh_total"):
            return linha
    return None


def calcular(linhas):
    ultima = ultima_linha_valida(linhas)
    if ultima is None:
        print("O arquivo existe mas nao tem leitura de energia ainda.")
        sys.exit(1)

    total = float(ultima["kwh_total"])
    solar = float(ultima["kwh_solar"])
    banco = float(ultima["kwh_banco"])
    rede = float(ultima["kwh_rede"])
    renovavel = solar + banco

    # CO2 que deixou de sair da rede
    co2_rede_evitado = renovavel * FATOR_SIN_KG_POR_KWH

    # CO2 evitado em relacao a gasolina, considerando toda a energia entregue
    km_rodados = total * EFICIENCIA_EV_KM_POR_KWH
    litros_equivalentes = km_rodados / CONSUMO_GASOLINA_KM_POR_LITRO
    co2_gasolina_evitado = litros_equivalentes * CO2_GASOLINA_KG_POR_LITRO
    co2_eletrico = rede * FATOR_SIN_KG_POR_KWH
    co2_liquido = co2_gasolina_evitado - co2_eletrico

    # economia em reais
    ponta = sum(1 for l in linhas if 18 <= int(l["horario"][11:13]) < 21)
    fracao_ponta = ponta / len(linhas) if linhas else 0
    tarifa_media = TARIFA_PONTA * fracao_ponta + TARIFA_FORA_PONTA * (1 - fracao_ponta)
    economia = renovavel * tarifa_media
    custo_rede = rede * tarifa_media

    # projecao anual: a mesma participacao renovavel, no volume de uma estacao real
    kwh_ano = VAGAS * SESSOES_POR_VAGA_DIA * KWH_POR_SESSAO * DIAS_POR_ANO
    fracao_renovavel = (renovavel / total) if total else 0
    renovavel_ano = kwh_ano * fracao_renovavel
    km_ano = kwh_ano * EFICIENCIA_EV_KM_POR_KWH
    co2_gasolina_ano = (km_ano / CONSUMO_GASOLINA_KM_POR_LITRO) * CO2_GASOLINA_KG_POR_LITRO
    co2_rede_ano = (kwh_ano - renovavel_ano) * FATOR_SIN_KG_POR_KWH
    economia_ano = renovavel_ano * tarifa_media

    return {
        "leituras": len(linhas), "total": total, "solar": solar, "banco": banco,
        "rede": rede, "renovavel": renovavel,
        "co2_eletrico": co2_eletrico,
        "kwh_ano": kwh_ano, "renovavel_ano": renovavel_ano, "km_ano": km_ano,
        "co2_gasolina_ano": co2_gasolina_ano, "co2_rede_ano": co2_rede_ano,
        "co2_liquido_ano": co2_gasolina_ano - co2_rede_ano,
        "economia_ano": economia_ano,
        "pct_renovavel": (renovavel / total * 100) if total else 0,
        "co2_rede_evitado": co2_rede_evitado, "km_rodados": km_rodados,
        "co2_gasolina_evitado": co2_gasolina_evitado, "co2_liquido": co2_liquido,
        "tarifa_media": tarifa_media, "economia": economia, "custo_rede": custo_rede,
    }


def barra(valor, total, largura=24):
    cheio = int((valor / total) * largura) if total else 0
    return "#" * cheio + "." * (largura - cheio)


def imprimir(r):
    print("\n=== GoodWe Charge - impacto da operacao ===\n")
    print(f"Leituras processadas: {r['leituras']}")
    print(f"Energia entregue:     {r['total']:.2f} kWh\n")

    print("Origem da energia")
    print(f"  solar   {r['solar']:6.2f} kWh  {barra(r['solar'], r['total'])}")
    print(f"  bateria {r['banco']:6.2f} kWh  {barra(r['banco'], r['total'])}")
    print(f"  rede    {r['rede']:6.2f} kWh  {barra(r['rede'], r['total'])}")
    print(f"  renovavel: {r['pct_renovavel']:.0f}% do total\n")

    print("Pegada de carbono")
    print(f"  evitado da rede:       {r['co2_rede_evitado'] * 1000:.1f} g CO2")
    print(f"  equivale a rodar:      {r['km_rodados']:.0f} km")
    print(f"  evitado vs gasolina:   {r['co2_gasolina_evitado']:.2f} kg CO2")
    print(f"  emitido pela recarga:  {r['co2_eletrico']:.3f} kg CO2")
    print(f"  saldo liquido:         {r['co2_liquido']:.2f} kg CO2 evitados\n")

    print("Custo")
    print(f"  tarifa media aplicada: R$ {r['tarifa_media']:.2f}/kWh")
    print(f"  economia com sol e bateria: R$ {r['economia']:.2f}")
    print(f"  gasto com energia da rede:  R$ {r['custo_rede']:.2f}\n")

    print("Projecao para a estacao em operacao")
    print(f"  volume anual:          {r['kwh_ano']:,.0f} kWh em {VAGAS} vagas")
    print(f"  atendido por renovavel:{r['renovavel_ano']:,.0f} kWh")
    print(f"  CO2 evitado no ano:    {r['co2_liquido_ano'] / 1000:.1f} toneladas")
    print(f"  economia no ano:       R$ {r['economia_ano']:,.0f}\n")

    print(f"Relatorio salvo em {SAIDA}")


def salvar_markdown(r):
    os.makedirs("docs", exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        f.write("# Impacto da operacao\n\n")
        f.write(f"Gerado a partir de {r['leituras']} leituras do `dados/sessoes.csv`.\n\n")
        f.write("## Energia\n\n")
        f.write("| Fonte | kWh | Participacao |\n|---|---|---|\n")
        for nome, valor in [("Solar", r["solar"]), ("Bateria da estacao", r["banco"]),
                            ("Rede", r["rede"])]:
            pct = (valor / r["total"] * 100) if r["total"] else 0
            f.write(f"| {nome} | {valor:.2f} | {pct:.0f}% |\n")
        f.write(f"| **Total** | **{r['total']:.2f}** | 100% |\n\n")

        f.write("## Carbono\n\n")
        f.write(f"- CO2 evitado por nao usar a rede: **{r['co2_rede_evitado'] * 1000:.1f} g**\n")
        f.write(f"- Autonomia equivalente: **{r['km_rodados']:.0f} km**\n")
        f.write(f"- CO2 evitado em relacao a um carro a gasolina: **{r['co2_gasolina_evitado']:.2f} kg**\n")
        f.write(f"- Saldo liquido: **{r['co2_liquido']:.2f} kg de CO2**\n\n")

        f.write("## Custo\n\n")
        f.write(f"- Tarifa media aplicada: R$ {r['tarifa_media']:.2f}/kWh\n")
        f.write(f"- Economia com sol e bateria: **R$ {r['economia']:.2f}**\n")
        f.write(f"- Gasto com energia da rede: R$ {r['custo_rede']:.2f}\n\n")

        f.write("## Projecao para a estacao em operacao\n\n")
        f.write(f"Mantendo a participacao renovavel medida ({r['pct_renovavel']:.0f}%) "
                f"em uma estacao de {VAGAS} vagas com {SESSOES_POR_VAGA_DIA} sessoes "
                f"por vaga ao dia e {KWH_POR_SESSAO} kWh por sessao:\n\n")
        f.write(f"- Energia entregue no ano: **{r['kwh_ano']:,.0f} kWh**\n")
        f.write(f"- Atendido por sol e bateria: **{r['renovavel_ano']:,.0f} kWh**\n")
        f.write(f"- CO2 evitado em relacao a frota a gasolina: "
                f"**{r['co2_liquido_ano'] / 1000:.1f} toneladas por ano**\n")
        f.write(f"- Economia na conta de energia: **R$ {r['economia_ano']:,.0f} por ano**\n\n")

        f.write("## Premissas\n\n")
        f.write(f"- Fator de emissao do SIN: {FATOR_SIN_KG_POR_KWH * 1000:.1f} g CO2/kWh "
                "(MCTI, fator medio mensal publicado no SIRENE)\n")
        f.write(f"- Carro a gasolina: {CO2_GASOLINA_KG_POR_LITRO} kg CO2 por litro, "
                f"{CONSUMO_GASOLINA_KM_POR_LITRO} km/l\n")
        f.write(f"- Carro eletrico: {EFICIENCIA_EV_KM_POR_KWH} km/kWh\n")
        f.write(f"- Tarifa fora de ponta R$ {TARIFA_FORA_PONTA}/kWh, "
                f"ponta R$ {TARIFA_PONTA}/kWh (18h as 21h)\n")


if __name__ == "__main__":
    linhas = ler_csv(ARQUIVO_CSV)
    resultado = calcular(linhas)
    imprimir(resultado)
    salvar_markdown(resultado)
