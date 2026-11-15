"""Regression checks for Trade Republic imports (no real customer data)."""
import unittest
from unittest.mock import patch
from io import BytesIO

from portfolio_optimizer.trade_republic_import import (
    category, number, parse_broker_csv, parse_statement_pdf,
)


class TradeRepublicImportTests(unittest.TestCase):
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
        self.assertEqual(got["BTC"], 0.5)
        self.assertEqual(counts["DIVIDEND"], 1)
        self.assertEqual(len(audit[audit["Status"].str.contains("Manuell prüfen")]), 1)

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
        with patch("pdfplumber.open", return_value=FakePdf()):
            result = parse_statement_pdf(b"%PDF-test")
        self.assertEqual(len(result.positions), 2)
        self.assertAlmostEqual(result.positions["Wert EUR"].sum(), 300)
        self.assertEqual(result.warnings, [])


if __name__ == "__main__":
    unittest.main()
