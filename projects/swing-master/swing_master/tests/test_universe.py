"""F&O universe selection: instrument-master filter, NSE list file, and the ALL escape hatch."""
import tempfile
import unittest
from pathlib import Path

from swing_master.data.universe import load_fno_list, select_universe
from swing_master.schemas import Instrument


def _inst(sym, fut=True, index=False):
    return Instrument(sym, sym, "Index" if index else "Test", "INDEX" if index else "EQ", 1, index, fut, index, 0.0)


UNIVERSE = [_inst("NIFTY", index=True), _inst("INDIAVIX", fut=False, index=True),
            _inst("RELIANCE"), _inst("TCS"), _inst("SMALLCO", fut=False)]

NSE_FILE = """UNDERLYING                                        ,SYMBOL    ,OCT-26    ,NOV-26    ,DEC-26
Derivatives on Individual Securities              ,          ,          ,          ,
RELIANCE INDUSTRIES LTD                           ,RELIANCE  ,500       ,500       ,500
UNDERLYING                                        ,SYMBOL    ,OCT-26    ,NOV-26    ,DEC-26
TATA CONSULTANCY SERV LT                          ,TCS       ,          ,175       ,175
HINDUSTAN AERONAUTICS LTD                         ,HAL       ,150       ,150       ,150
"""


class UniverseTests(unittest.TestCase):
    def test_fno_uses_has_futures(self):
        kept, info = select_universe(UNIVERSE, "FNO")
        self.assertEqual([i.symbol for i in kept], ["NIFTY", "RELIANCE", "TCS"])
        self.assertEqual(sorted(info["excluded"]), ["INDIAVIX", "SMALLCO"])
        self.assertEqual((info["stocks"], info["indices"]), (2, 1))

    def test_all_keeps_everything(self):
        kept, info = select_universe(UNIVERSE, "all")
        self.assertEqual(len(kept), len(UNIVERSE))
        self.assertEqual(info["mode"], "ALL")

    def test_bad_mode_rejected(self):
        with self.assertRaises(ValueError):
            select_universe(UNIVERSE, "NIFTY50")

    def test_nse_lot_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fo_mktlots.csv"
            path.write_text(NSE_FILE)
            lots = load_fno_list(path)
        self.assertEqual(lots, {"RELIANCE": 500, "TCS": 175, "HAL": 150})
        kept, info = select_universe(UNIVERSE, "FNO", lots)
        self.assertEqual({i.symbol: i.lot_size for i in kept}, {"NIFTY": 1, "RELIANCE": 500, "TCS": 175})
        self.assertIn("SMALLCO", info["excluded"])
        self.assertEqual(info["missing_data"], ["HAL"])  # on the F&O list, but the data source has no bars for it

    def test_plain_symbol_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fno.txt"
            path.write_text("reliance\nSMALLCO, 900\n")
            lots = load_fno_list(path)
        self.assertEqual(lots, {"RELIANCE": None, "SMALLCO": 900})
        kept, _ = select_universe(UNIVERSE, "FNO", lots)
        self.assertEqual([i.symbol for i in kept], ["NIFTY", "RELIANCE", "SMALLCO"])
        self.assertTrue(all(i.has_futures for i in kept))


if __name__ == "__main__":
    unittest.main()
