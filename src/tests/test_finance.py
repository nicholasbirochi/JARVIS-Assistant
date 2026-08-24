from datetime import datetime

import openpyxl
import pytest

from finance import expenses_by_category, format_month, load_snapshot, salary_by_month, summarize_finances


def _build_workbook(path):
    """A tiny synthetic workbook matching Patrimônio.xlsx's real, live-
    confirmed shape (see finance.py's module docstring) -- not the
    user's real file, which must never be hardcoded into a test."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Variáveis"

    ws.append(["Valores Previsíveis", None, None, None, None, None, None])
    ws.append([None] * 7)
    ws.append(["Mensalidades/Entradas", None, None, None, "Mensalidades/Presentes/Despesas", None, None])
    header = ["Tipo", "Dinheiro", "Mês/Ano", None, "Tipo", "Dinheiro", "Quantidade", None]
    header += ["Inter BR", "Inter US", "Itaú", "Mercado Pago", None]
    header += ["Inter BR", "Inter US", "Itaú", "Mercado Pago", None]
    header += ["Inter BR", "Inter US", "Itaú", "Mercado Pago"]
    ws.append(header)

    # Real data row 1 (sheet row 5): income + expense + the one bank snapshot row.
    row = ["Salário", 1000.0, datetime(2026, 1, 1), None, "Academia", 100.0, 2, None]
    row += [5000.0, 200.0, 0.0, 0.0, None]  # invested (Inter US in USD)
    row += [500.0, 20.0, 0.0, 0.0, None]  # yield (Inter US in USD)
    row += [5500.0, 1100.0, 0.0, 0.0]  # total (already BRL-converted for every bank)
    ws.append(row)

    # A second income-only row, no expense/bank data on it.
    ws.append(["Salário", 1100.0, datetime(2026, 2, 1), None, None, None, None])
    # A one-off, non-Salário income entry -- must be excluded from the
    # salary trend (it would make the line noisy, not informative).
    ws.append(["Reembolso", 500.0, datetime(2026, 2, 15), None, None, None, None])
    # A future, unfilled income row -- must be excluded (Dinheiro is empty).
    ws.append(["Salário", None, datetime(2026, 3, 1), None, None, None, None])

    contas = wb.create_sheet("Contas")
    contas.append(["Valor Bruto", "Despesas", "→", "Valor Previsto", "Luxos", "→", "Grana Final"])
    contas.append([2100.0, -200.0, None, 1900.0, 700.0, None, 2600.0])

    wb.save(path)


@pytest.fixture
def workbook_path(tmp_path):
    path = tmp_path / "Patrimônio.xlsx"
    _build_workbook(path)
    return path


def test_load_snapshot_parses_income_excluding_future_empty_rows(workbook_path):
    snapshot = load_snapshot(workbook_path)

    assert len(snapshot.income) == 3  # not the 4th, empty-amount row
    assert snapshot.income[0].kind == "Salário"
    assert snapshot.income[0].amount == 1000.0
    assert snapshot.income[1].amount == 1100.0
    assert snapshot.income[2].kind == "Reembolso"


def test_load_snapshot_expense_total_multiplies_by_quantity(workbook_path):
    snapshot = load_snapshot(workbook_path)

    assert len(snapshot.expenses) == 1
    expense = snapshot.expenses[0]
    assert expense.kind == "Academia"
    assert expense.unit_amount == 100.0
    assert expense.quantity == 2
    assert expense.total == 200.0


def test_load_snapshot_bank_snapshot_marks_inter_us_as_usd(workbook_path):
    snapshot = load_snapshot(workbook_path)

    by_bank = {b.bank: b for b in snapshot.banks}
    assert by_bank["Inter BR"].currency == "BRL"
    assert by_bank["Inter US"].currency == "USD"
    assert by_bank["Inter US"].invested == 200.0
    assert by_bank["Inter US"].total_brl == 1100.0  # BRL-converted, not the raw USD figure


def test_load_snapshot_reads_contas_aggregates(workbook_path):
    snapshot = load_snapshot(workbook_path)

    assert snapshot.gross_value == 2100.0
    assert snapshot.total_expenses == -200.0
    assert snapshot.projected_value == 1900.0
    assert snapshot.luxuries == 700.0
    assert snapshot.final_money == 2600.0


def test_expenses_by_category_sorted_by_total_descending(workbook_path):
    snapshot = load_snapshot(workbook_path)

    result = expenses_by_category(snapshot)

    assert result == [("Academia", 200.0)]


def test_summarize_finances_mentions_total_and_banks(workbook_path):
    snapshot = load_snapshot(workbook_path)

    text = summarize_finances(snapshot)

    assert "2.600,00" in text  # Brazilian-format thousands/decimal separators
    assert "Inter BR" in text
    assert "Inter US" in text
    assert "Academia" in text


def test_format_month_uses_portuguese_abbreviations():
    assert format_month(datetime(2026, 2, 1)) == "fev/26"
    assert format_month(datetime(2025, 12, 15)) == "dez/25"


def test_salary_by_month_excludes_non_salary_income_and_sorts_chronologically(workbook_path):
    snapshot = load_snapshot(workbook_path)

    result = salary_by_month(snapshot)

    assert [amount for _when, amount in result] == [1000.0, 1100.0]  # not the Reembolso entry
    assert result[0][0] < result[1][0]  # chronological order
