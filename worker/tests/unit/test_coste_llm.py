"""Tests de `radar.coste_llm.calcular_coste_eur` -- pura, sin red ni BD."""

from radar.coste_llm import calcular_coste_eur


def test_gpt_5_6_sol_coste_esperado():
    # 100.000 tokens entrada + 10.000 salida, precio 4/20 $ por millón.
    coste = calcular_coste_eur("gpt-5.6-sol", 100_000, 10_000)
    assert round(coste, 4) == round(100_000 / 1_000_000 * 4.00 + 10_000 / 1_000_000 * 20.00, 4)


def test_gpt_5_6_luna_es_mas_barato_que_sol():
    coste_luna = calcular_coste_eur("gpt-5.6-luna", 1_000_000, 1_000_000)
    coste_sol = calcular_coste_eur("gpt-5.6-sol", 1_000_000, 1_000_000)
    assert coste_luna < coste_sol


def test_modelo_desconocido_no_inventa_coste():
    """Principio 5: un modelo sin precio verificado da 0.0, nunca un
    número inventado."""
    assert calcular_coste_eur("modelo-que-no-existe", 1_000_000, 1_000_000) == 0.0


def test_cero_tokens_es_coste_cero():
    assert calcular_coste_eur("gpt-5.6-sol", 0, 0) == 0.0


def test_claude_sonnet_5_precio_verificado():
    coste = calcular_coste_eur("claude-sonnet-5", 1_000_000, 1_000_000)
    assert round(coste, 2) == 12.00  # 2 + 10 $/millón
