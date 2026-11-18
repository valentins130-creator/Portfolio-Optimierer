"""Regression checks for Trade Republic imports (no real customer data)."""
import sys
import unittest
from types import SimpleNamespace

import pandas as pd
from unittest.mock import patch
from io import BytesIO

from portfolio_optimizer.trade_republic_import import (
    category, number, parse_broker_csv, parse_statement_pdf, confirmed_positions, is_broker_csv,
)


class TradeRepublicImportTests(unittest.TestCase):
    def test_date_and_datetime_columns_coexist(self):
        data = ("datetime,date,type,symbol,shares,name,asset_class\n"
                "2026-01-01T10:00:00Z,2026-01-01,BUY,ABC,2,Example,STOCK\n"
                "2026-01-02T10:00:00Z,2026-01-02,DIVIDEND,ABC,10,Example,STOCK\n")
        holdings, audit, _ = parse_broker_csv(data.encode())
        self.assertEqual(len(audit), 2)
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings.iloc[0]["Anteile"], 2)

    def test_german_numbers_and_risk_categories(self):
        self.assertEqual(number("17.614,25"), 17614.25)
        self.assertEqual(category("S&P 500 5X Daily Leveraged USD", section="BROKERAGE"),
                         "Derivate/Leveraged")
        self.assertEqual(category("Core MSCI World USD (Acc)", section="BROKERAGE"),
                         "Aktien-ETFs/Fonds")
        self.assertEqual(category("Boeing Feb. 2027", section="ZINSPRODUKTE"), "Anleihen")

    def test_cashflows_do_not_mint_shares_and_sells_reduce_shares(self):
        csv = ("date,type,symbol,shares,name,asset_class\n"
               "2026-01-01,BUY,US1234567890,10,Example,STOCK\n"
               "2026-02-01,SELL,US1234567890,-3,Example,STOCK\n"
               "2026-02-02,DIVIDEND,US1234567890,99,Example,STOCK\n"
               "2026-02-03,FREE_RECEIPT,BTC,0.5,Bitcoin,CRYPTO\n"
               "2026-02-04,INTEREST_PAYMENT,US1234567890,15,Example,STOCK\n"
               "2026-02-05,SPLIT,US1234567890,2,Example,STOCK\n")
        holdings, audit, counts = parse_broker_csv(csv.encode())
        got = dict(zip(holdings["ISIN/Symbol"], holdings["Anteile"]))
        self.assertEqual(got["US1234567890"], 7)
        self.assertNotIn("BTC", got)
        self.assertTrue(confirmed_positions(holdings).empty)
        self.assertEqual(counts["DIVIDEND"], 1)
        self.assertEqual(len(audit[audit["Status"].str.contains("Manuell prüfen")]), 2)


    def test_malformed_and_unknown_events_remain_visible(self):
        content = ("symbol;shares;type;datetime;asset_class\n"
                   "ABC;10;BUY;2026-01-01;STOCK\n"
                   "ABC;bad;SELL;2026-01-02;STOCK\n"
                   "ABC;inf;BUY;2026-01-02;STOCK\n"
                   "ABC;-2;BUY;2026-01-02;STOCK\n"
                   "ABC;3;BUY;invalid;STOCK\n"
                   "ABC;50;SURPRISE;2026-01-02;STOCK\n"
                   "ABC;99;DEPOSIT;2026-01-02;STOCK\n").encode()
        holdings, audit, _ = parse_broker_csv(content)
        self.assertEqual(len(audit), 7)
        self.assertEqual(holdings.iloc[0]["Anteile"], 10)
        self.assertEqual(audit["Bestandsänderung"].sum(), 10)
        self.assertTrue(confirmed_positions(holdings).empty)
        self.assertTrue(is_broker_csv(b"\xef\xbb\xbf" + content))
        from portfolio_optimizer.portfolio import read_transactions_csv
        with self.assertRaises(ValueError):
            read_transactions_csv(content)

    def test_gate_rejects_invalid_or_unconfirmed_positions(self):
        frame = pd.DataFrame({"ISIN/Symbol": list("ABCDEFG"),
                              "Anlageklasse": ["Aktien"] * 7,
                              "Anteile": [1, 1, float("inf"), -1, 1, 1, 1],
                              "Wert EUR": [2, 2, 2, 2, float("nan"), 2, 2],
                              "Bestätigt": [True, False, True, True, True, "True", True]})
        frame.loc[6, "ISIN/Symbol"] = ""
        self.assertEqual(list(confirmed_positions(frame).index), [0])
        self.assertTrue(confirmed_positions(frame.drop(columns="Bestätigt")).empty)

    def test_pdf_snapshot_reconciles_to_total(self):
        sample = ("VERMÖGENSÜBERSICHT\n"
                  "zum 15.11.2026\n"
                  "GESAMT 300,00 EUR\n"
                  "BROKERAGE\n"
                  "2 Stk. Example AG 100,00 200,00\n"
                  "ISIN: DE0001234567\n"
                  "CASH\n"
                  "Cashkonto 100,00 EUR\n")
        class FakePage:
            def extract_text(self):
                return sample
        class FakePdf:
            pages = [FakePage()]
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        # ohne installiertes pdfplumber testbar: Modul durch eine Attrappe ersetzen
        with patch.dict(sys.modules, {"pdfplumber": SimpleNamespace(open=lambda _: FakePdf())}):
            result = parse_statement_pdf(b"%PDF-test")
        self.assertEqual(len(result.positions), 2)
        self.assertAlmostEqual(result.positions["Wert EUR"].sum(), 300)
        self.assertEqual(result.warnings, [])
        self.assertTrue(confirmed_positions(result.positions).empty)
        result.positions["Bestätigt"] = True
        self.assertEqual(len(confirmed_positions(result.positions)), 2)
        result.positions.loc[0, "ISIN/Symbol"] = ""
        self.assertEqual(len(confirmed_positions(result.positions)), 1)
        result.positions.loc[0, "ISIN/Symbol"] = "EUR"
        self.assertTrue(confirmed_positions(result.positions).empty)

    def test_missing_pdfplumber_gives_a_clear_message(self):
        with patch.dict(sys.modules, {"pdfplumber": None}):
            with self.assertRaisesRegex(ValueError, "pdfplumber"):
                parse_statement_pdf(b"%PDF-test")

    def test_broker_csv_keeps_price_or_amount(self):
        csv = ("date,type,symbol,shares,amount,asset_class\n"
               "2026-01-05,BUY,DE0007164600,4,-720,00,STOCK\n").replace("-720,00", '"-720,00"')
        _, audit, _ = parse_broker_csv(csv.encode())
        self.assertAlmostEqual(audit.loc[0, "Kurs"], 180.0)


if __name__ == "__main__":
    unittest.main()
