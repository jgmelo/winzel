"""Linha do tempo: séries de contagens e métricas, milestones e os dois gráficos.

O gráfico do terminal usa o plotext; o detalhado, o matplotlib (sem janela nos testes).
"""

import asyncio
import json
from datetime import datetime

import plotext
import pytest
from tests.fakes import FakeFileSystem, FixedClock, make_context, sample
from textual.widgets import Select

from winzel.checks import get_check
from winzel.filesystem import GB, DiskUsage
from winzel.plots import figure, from_payload, launch, payload
from winzel.snapshot import compare_snapshot, take_snapshot
from winzel.timeline import Series, build_timeline, draw_terminal_plot, visible_milestones
from winzel.ui.app import WinzelApp

pytestmark = [pytest.mark.fase4, pytest.mark.interface]

CHECKS = [get_check("programs"), get_check("disk_c")]
AGORA = datetime(2026, 11, 10)


def dia(n):
    return datetime(2026, 11, n, 9, 0)


def gravar_historico(banco, livres=(50, 40, 30), erro_no_segundo=False):
    """Um snapshot por dia, com o C: cada vez mais cheio e um programa a mais por dia."""
    clock = FixedClock(dia(1))
    programas = list(sample("programs"))
    for i, livre in enumerate(livres):
        fs = FakeFileSystem()
        fs.disks["C:\\"] = DiskUsage(total=1000 * GB, free=int(livre * 10 * GB))
        resposta = programas[: 6 + i]
        if erro_no_segundo and i == 1:
            resposta = RuntimeError("falhou")
        take_snapshot(
            banco, make_context({"programs": resposta}, clock=clock, fs=fs), CHECKS, "auto"
        )
        clock.advance(days=1)
    return clock


# --- dados ----------------------------------------------------------------------


def test_cada_metrica_vira_uma_serie_ao_longo_dos_snapshots(banco):
    """Dados três snapshots com 50%, 40% e 30% livres no C:, então a série tem os três pontos."""
    gravar_historico(banco)

    linha = build_timeline(banco, CHECKS)

    serie = linha.get("metric:disk_c_free_pct")
    assert serie.label == "Espaço livre no C: (%)"
    assert serie.points == [(dia(1), 50.0), (dia(2), 40.0), (dia(3), 30.0)]


def test_cada_categoria_do_inventario_vira_uma_serie_de_quantidade(banco):
    """Dados programas crescendo, então a série "Programas (quantidade)" acompanha."""
    gravar_historico(banco)

    serie = build_timeline(banco, CHECKS).get("count:programs")

    assert serie.label == "Programas (quantidade)"
    assert [v for _, v in serie.points] == [4.0, 5.0, 6.0]


def test_snapshot_em_que_a_categoria_falhou_fica_fora_da_serie(banco):
    """Dado erro em programs no 2º snapshot, então a série não tem ponto nesse dia."""
    gravar_historico(banco, erro_no_segundo=True)

    serie = build_timeline(banco, CHECKS).get("count:programs")

    assert [w for w, _ in serie.points] == [dia(1), dia(3)]


def test_series_comecam_pelas_metricas_e_a_padrao_e_o_espaco_livre_no_c(banco):
    """Dado o histórico, então métricas vêm antes das contagens; a padrão é % livre no C:."""
    gravar_historico(banco)

    linha = build_timeline(banco, CHECKS)

    assert [s.key for s in linha.series] == [
        "metric:disk_c_free_pct",
        "metric:disk_c_free_gb",
        "count:programs",
    ]
    assert linha.default_key() == "metric:disk_c_free_pct"


def test_milestones_entram_na_linha_do_tempo_com_data_e_nome(banco):
    """Dado o milestone "limpo" no 2º snapshot, então a linha do tempo o traz com a data dele."""
    gravar_historico(banco)
    banco.create_milestone(2, "limpo", "", AGORA)

    linha = build_timeline(banco, CHECKS)

    assert linha.milestones == [(dia(1), "linha-de-base"), (dia(2), "limpo")]


def test_so_milestones_dentro_do_periodo_da_serie_sao_desenhados():
    """Dada uma série de 2 a 4/11, então um milestone de 1/11 fica de fora."""
    serie = Series("k", "x", "%", [(dia(2), 1.0), (dia(4), 2.0)])

    visiveis = visible_milestones(serie, [(dia(1), "antes"), (dia(3), "dentro")])

    assert visiveis == [(dia(3), "dentro")]


def test_metricas_gravadas_mantem_o_status_ao_recomparar(banco):
    """Dado o C: 🟡 num snapshot, quando troco a referência, então o C: continua 🟡."""
    gravar_historico(banco, livres=(15,))
    snapshot = banco.latest_snapshot()

    report = compare_snapshot(banco, CHECKS, snapshot, None)

    disco = next(o for o in report.outcomes if o.check_id == "disk_c")
    assert disco.status.value == "warn"
    assert disco.result.summary == "150 GB livres de 1000 GB (15%)"


# --- gráficos -------------------------------------------------------------------


def serie_exemplo():
    return Series(
        "metric:disk_c_free_pct",
        "Espaço livre no C: (%)",
        "%",
        [(dia(1), 50.0), (dia(2), 40.0), (dia(3), 30.0)],
    )


def test_grafico_no_terminal_mostra_titulo_e_milestones():
    """Dado o milestone "limpo", então o gráfico do terminal mostra o título e o rótulo dele."""
    draw_terminal_plot(plotext, serie_exemplo(), [(dia(2), "limpo")])
    plotext.plotsize(80, 20)

    desenho = plotext.build()

    assert "Espaço livre no C: (%)" in desenho
    assert "limpo" in desenho


def test_grafico_detalhado_tem_uma_linha_vertical_rotulada_por_milestone():
    """Dados dois milestones no período, então o matplotlib desenha duas linhas rotuladas."""
    fig = figure(serie_exemplo(), [(dia(1), "linha-de-base"), (dia(2), "limpo")])

    (ax,) = fig.axes
    verticais = [ln for ln in ax.get_lines() if ln.get_linestyle() == "--"]
    assert len(verticais) == 2
    assert [t.get_text() for t in ax.texts] == ["linha-de-base", "limpo"]
    assert ax.get_title() == "Espaço livre no C: (%)"


def test_grafico_detalhado_pode_ser_salvo_como_imagem(tmp_path):
    """Dada a série, então o gráfico do matplotlib é gerado como PNG sem abrir janela."""
    caminho = tmp_path / "grafico.png"

    figure(serie_exemplo(), []).savefig(caminho)

    assert caminho.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_dados_do_grafico_vao_e_voltam_em_json():
    """Dada a série com um milestone, quando converto para JSON e de volta, então nada se perde."""
    serie, marcos = from_payload(json.loads(json.dumps(payload(serie_exemplo(), [(dia(2), "x")]))))

    assert serie.points == serie_exemplo().points
    assert marcos == [(dia(2), "x")]


def test_grafico_detalhado_abre_em_processo_separado(tmp_path):
    """Dada a série, quando abro o gráfico, então inicio `python -m winzel.plots` à parte."""
    chamadas = []

    caminho = launch(serie_exemplo(), [], popen=chamadas.append)

    (comando,) = chamadas
    assert comando[1:3] == ["-m", "winzel.plots"]
    assert comando[3] == str(caminho)
    assert json.loads(caminho.read_text(encoding="utf-8"))["label"] == "Espaço livre no C: (%)"
    caminho.unlink()


# --- aba Linha do tempo ---------------------------------------------------------


def app_com_historico(banco, launcher):
    clock = gravar_historico(banco)
    fs = FakeFileSystem()
    fs.disks["C:\\"] = DiskUsage(total=1000 * GB, free=200 * GB)
    ctx = make_context({"programs": sample("programs")}, clock=clock, fs=fs)
    return WinzelApp(banco, ctx, CHECKS, plot_launcher=launcher)


def test_aba_linha_do_tempo_lista_as_series_e_comeca_pelo_espaco_no_c(banco):
    """Dado o histórico, então a aba Linha do tempo começa pela série % livre no C:."""
    app = app_com_historico(banco, lambda *a: None)

    async def cenario():
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            seletor = app.query_one("#timeline-series", Select)
            assert seletor.value == "metric:disk_c_free_pct"
            assert [v for _, v in app.selected_series().points] == [50.0, 40.0, 30.0, 20.0]

    asyncio.run(cenario())


def test_tecla_p_abre_o_grafico_da_serie_escolhida(banco):
    """Dada a série "Programas (quantidade)", quando pressiono p, então o gráfico dela abre."""
    abertos = []
    app = app_com_historico(banco, lambda serie, marcos: abertos.append((serie, marcos)))

    async def cenario():
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#timeline-series", Select).value = "count:programs"
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()

    asyncio.run(cenario())
    ((serie, marcos),) = abertos
    assert serie.label == "Programas (quantidade)"
    assert marcos == [(dia(1), "linha-de-base")]
