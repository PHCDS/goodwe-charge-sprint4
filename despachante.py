"""
GoodWe Charge - Sprint 4
Despachante de energia.

Recebe o status do carregador pelo MQTT, decide de onde a energia deve sair e
com qual potencia, manda esse comando de volta para o equipamento e grava tudo
em CSV.

A decisao pesa quatro coisas: quanto o inversor esta gerando, quanta carga
sobrou na bateria da estacao, se e horario de ponta e quanto falta para o carro
chegar no limite.

Instalar antes: pip install paho-mqtt
Rodar:          python scripts/despachante.py
Testar a logica sem rede: python scripts/despachante.py --teste
"""

import csv
import json
import os
import sys
from datetime import datetime

BROKER = "broker.hivemq.com"
PORTA = 1883
TOPICO_STATUS = "goodwe/fiap1cc/carregador01/status"
TOPICO_COMANDO = "goodwe/fiap1cc/carregador01/comando"

# --- parametros da estacao ---
POTENCIA_MAX_KW = 7.4          # wallbox AC
LIMITE_BATERIA = 80            # alvo de carga do veiculo, em %
BANCO_CAPACIDADE_KWH = 10.8    # 2 modulos de 5.4 kWh
BANCO_RESERVA_KWH = 1.0        # nao descarrega abaixo disso
SOLAR_MINIMO_KW = 1.5          # abaixo disso o sol nao sustenta a carga
PONTA_INICIO, PONTA_FIM = 18, 21   # horario de ponta, tarifa mais cara
POTENCIA_REDUZIDA_KW = 3.0     # potencia usada quando a rede e a unica opcao na ponta
URGENTE_PONTOS = 15            # faltando menos que isso para o limite, a sessao e urgente

ARQUIVO_CSV = "dados/sessoes.csv"
ARQUIVO_JSON = "dados/status.json"

sessao = {
    "kwh_total": 0.0,
    "kwh_solar": 0.0,
    "kwh_banco": 0.0,
    "kwh_rede": 0.0,
    "ultima_hora": None,
    "leituras": 0,
    "ultimo_comando": None,
}


def e_ponta(hora):
    """Entre 18h e 21h a energia da rede custa mais caro."""
    return PONTA_INICIO <= hora < PONTA_FIM


def decidir(leitura, hora):
    """
    Coracao do despachante.

    Recebe a leitura do carregador e a hora atual. Devolve a potencia que deve
    ser entregue, a fonte prevista e o motivo da decisao em texto.

    O motivo e tao importante quanto o numero: e ele que aparece no painel e
    explica para o operador por que a recarga esta mais lenta.
    """
    bateria = leitura["bateria"]
    solar = leitura["solar_kw"]
    banco = leitura["banco_kwh"]
    status = leitura["status"]

    # 1. sessao encerrada ou carro no limite: nao ha o que despachar
    if status != "carregando":
        return 0.0, "nenhuma", "sem sessao ativa"

    if bateria >= LIMITE_BATERIA:
        return 0.0, "nenhuma", f"bateria em {bateria}%, limite de {LIMITE_BATERIA}% atingido"

    urgente = (LIMITE_BATERIA - bateria) <= URGENTE_PONTOS

    # 2. o sol cobre a demanda cheia: melhor cenario, carrega no maximo
    if solar >= POTENCIA_MAX_KW:
        return POTENCIA_MAX_KW, "solar", "geracao solar cobre a demanda cheia"

    # 3. ha sol, mas nao o bastante: acompanha a geracao e evita puxar da rede
    if solar >= SOLAR_MINIMO_KW:
        banco_disponivel = banco - BANCO_RESERVA_KWH
        if banco_disponivel > 0.5 and urgente:
            return POTENCIA_MAX_KW, "bateria", (
                f"sessao perto do limite, bateria da estacao completa os {POTENCIA_MAX_KW} kW"
            )
        return round(solar, 1), "solar", f"acompanhando a geracao solar de {solar} kW"

    # 4. sol fraco: usa a bateria da estacao enquanto houver carga
    banco_disponivel = banco - BANCO_RESERVA_KWH
    if banco_disponivel > 0.5:
        potencia = POTENCIA_MAX_KW if urgente else round(min(POTENCIA_MAX_KW, banco_disponivel * 2), 1)
        return potencia, "bateria", f"pouco sol, descarregando a bateria da estacao ({banco} kWh)"

    # 5. sem sol e sem banco: sobra a rede. Na ponta, segura a potencia
    if e_ponta(hora) and not urgente:
        return POTENCIA_REDUZIDA_KW, "rede", (
            "horario de ponta sem geracao: potencia reduzida para cortar custo"
        )

    return POTENCIA_MAX_KW, "rede", "sem geracao e sem reserva, puxando da rede"


def preparar_arquivo():
    os.makedirs("dados", exist_ok=True)
    if not os.path.exists(ARQUIVO_CSV):
        with open(ARQUIVO_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "horario", "carregador", "bateria", "solar_kw", "banco_kwh",
                "banco_soc", "fonte", "status", "potencia_kw",
                "kwh_total", "kwh_solar", "kwh_banco", "kwh_rede", "decisao",
            ])


def acumular_energia(leitura, agora):
    """Energia = potencia x tempo, separada pela fonte que atendeu a sessao."""
    if sessao["ultima_hora"] is None:
        sessao["ultima_hora"] = agora
        return
    horas = (agora - sessao["ultima_hora"]).total_seconds() / 3600
    sessao["ultima_hora"] = agora

    if leitura["status"] != "carregando":
        return

    energia = leitura["potencia_kw"] * horas
    sessao["kwh_total"] += energia
    fonte = leitura["fonte"]
    if fonte == "solar":
        sessao["kwh_solar"] += energia
    elif fonte == "bateria":
        sessao["kwh_banco"] += energia
    else:
        sessao["kwh_rede"] += energia


def gravar(leitura, agora, decisao):
    with open(ARQUIVO_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            agora.strftime("%Y-%m-%d %H:%M:%S"),
            leitura["id"], leitura["bateria"], leitura["solar_kw"],
            leitura["banco_kwh"], leitura["banco_soc"], leitura["fonte"],
            leitura["status"], leitura["potencia_kw"],
            round(sessao["kwh_total"], 4), round(sessao["kwh_solar"], 4),
            round(sessao["kwh_banco"], 4), round(sessao["kwh_rede"], 4),
            decisao,
        ])

    painel = dict(leitura)
    painel["decisao"] = decisao
    painel["kwh_total"] = round(sessao["kwh_total"], 3)
    with open(ARQUIVO_JSON, "w", encoding="utf-8") as f:
        json.dump(painel, f, ensure_ascii=False, indent=2)


def ao_conectar(cliente, userdata, flags, rc):
    if rc == 0:
        print("Conectado no broker. Despachante no ar.\n")
        cliente.subscribe(TOPICO_STATUS)
    else:
        print("Falha na conexao, codigo", rc)


def ao_receber(cliente, userdata, mensagem):
    try:
        leitura = json.loads(mensagem.payload.decode())
        leitura.setdefault("banco_kwh", 0.0)
        leitura.setdefault("banco_soc", 0)
    except json.JSONDecodeError:
        print("Mensagem fora do formato esperado, ignorando")
        return

    agora = datetime.now()
    sessao["leituras"] += 1
    acumular_energia(leitura, agora)

    potencia, fonte, motivo = decidir(leitura, agora.hour)
    decisao = f"{potencia} kW via {fonte}: {motivo}"

    print("[{}] bateria {}% | sol {} kW | banco {} kWh ({}%) | {} | {} kWh".format(
        agora.strftime("%H:%M:%S"), leitura["bateria"], leitura["solar_kw"],
        leitura["banco_kwh"], leitura["banco_soc"], leitura["fonte"],
        round(sessao["kwh_total"], 3)))

    # so publica quando a decisao muda, para nao inundar o broker
    if decisao != sessao["ultimo_comando"]:
        sessao["ultimo_comando"] = decisao
        print(f"   >> {decisao}")
        if potencia == 0 and leitura["status"] == "carregando":
            cliente.publish(TOPICO_COMANDO, json.dumps({"acao": "parar", "motivo": motivo}))
        else:
            cliente.publish(TOPICO_COMANDO, json.dumps(
                {"acao": "potencia", "kw": potencia, "motivo": motivo}))

    gravar(leitura, agora, decisao)


def resumo():
    print("\n--- resumo da sessao ---")
    print("leituras recebidas:", sessao["leituras"])
    total = sessao["kwh_total"]
    print("energia entregue:", round(total, 2), "kWh")
    if total > 0:
        print("  solar  :", round(sessao['kwh_solar'], 2), "kWh",
              f"({sessao['kwh_solar'] / total * 100:.0f}%)")
        print("  bateria:", round(sessao['kwh_banco'], 2), "kWh",
              f"({sessao['kwh_banco'] / total * 100:.0f}%)")
        print("  rede   :", round(sessao['kwh_rede'], 2), "kWh",
              f"({sessao['kwh_rede'] / total * 100:.0f}%)")
    print("historico salvo em", ARQUIVO_CSV)
    print("\nPara ver o impacto: python scripts/impacto.py")


def teste():
    """Roda a logica de decisao em cenarios fixos, sem precisar de MQTT."""
    casos = [
        ("meio-dia de sol forte", {"bateria": 40, "solar_kw": 9.0, "banco_kwh": 6.0,
                                   "status": "carregando"}, 12),
        ("sol fraco, banco cheio", {"bateria": 40, "solar_kw": 0.5, "banco_kwh": 8.0,
                                    "status": "carregando"}, 16),
        ("noite de ponta, banco vazio", {"bateria": 40, "solar_kw": 0.0, "banco_kwh": 1.0,
                                         "status": "carregando"}, 19),
        ("ponta, mas sessao urgente", {"bateria": 72, "solar_kw": 0.0, "banco_kwh": 1.0,
                                       "status": "carregando"}, 19),
        ("madrugada sem sol", {"bateria": 30, "solar_kw": 0.0, "banco_kwh": 1.0,
                               "status": "carregando"}, 3),
        ("carro no limite", {"bateria": 81, "solar_kw": 9.0, "banco_kwh": 6.0,
                             "status": "carregando"}, 12),
        ("sol parcial", {"bateria": 40, "solar_kw": 4.0, "banco_kwh": 2.0,
                         "status": "carregando"}, 14),
    ]
    print("Cenarios de decisao\n")
    for nome, leitura, hora in casos:
        potencia, fonte, motivo = decidir(leitura, hora)
        print(f"{nome} ({hora}h)")
        print(f"   -> {potencia} kW via {fonte}: {motivo}\n")


if __name__ == "__main__":
    if "--teste" in sys.argv:
        teste()
        sys.exit(0)

    import paho.mqtt.client as mqtt

    preparar_arquivo()
    cliente = mqtt.Client()
    cliente.on_connect = ao_conectar
    cliente.on_message = ao_receber
    cliente.connect(BROKER, PORTA, 60)
    try:
        cliente.loop_forever()
    except KeyboardInterrupt:
        cliente.disconnect()
        resumo()
