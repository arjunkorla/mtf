from app.data.symbol_master_parser import parse_symbol_master_csv

VALID_ROW = "101000000016921,20 MICRONS LTD,0,1,0.01,INE144J01027,0915-1530|1815-1915:,2026-09-18,,NSE:20MICRONS-EQ,10,10,16921,20MICRONS,16921,-1.0,XX,101000000016921,None,1,2.0"
NOT_MTF_ROW = "10100000004,21ST CENTURY MGMT SERVICE,0,1,0.01,INE253B01015,0915-1530|1815-1915:,2026-09-18,,NSE:21STCENMGM-EQ,10,10,4,21STCENMGM,4,-1.0,XX,10100000004,None,0,0.0"
BE_SERIES_ROW = "10100000006240,3I INFOTECH LIMITED,0,1,0.01,INE748C01038,0915-1530|1815-1915:,2026-09-18,,NSE:3IINFOLTD-BE,10,10,6240,3IINFOLTD,6240,-1.0,XX,10100000006240,None,0,0.0"


def test_parses_valid_eq_row():
    result = parse_symbol_master_csv(VALID_ROW)
    assert result.rows_skipped == 0
    assert len(result.symbols) == 1
    s = result.symbols[0]
    assert s.symbol == "NSE:20MICRONS-EQ"
    assert s.company_name == "20 MICRONS LTD"
    assert s.isin == "INE144J01027"
    assert s.lot_size == 1
    assert s.is_mtf_eligible is True


def test_is_mtf_eligible_false_when_flag_is_zero():
    result = parse_symbol_master_csv(NOT_MTF_ROW)
    assert len(result.symbols) == 1
    assert result.symbols[0].is_mtf_eligible is False


def test_non_eq_series_is_filtered_not_counted_as_skip():
    result = parse_symbol_master_csv(BE_SERIES_ROW)
    assert result.symbols == []
    assert result.rows_skipped == 0  # deliberate filter, not a validation failure
    assert result.rows_seen == 1


def test_malformed_row_is_skipped_not_crashed():
    malformed = "too,few,columns"
    result = parse_symbol_master_csv(malformed)
    assert result.symbols == []
    assert result.rows_skipped == 1
    assert "columns" in result.skip_reasons_sample[0]


def test_bad_symbol_format_is_skipped():
    bad_symbol = VALID_ROW.replace("NSE:20MICRONS-EQ", "NOT_A_VALID_SYMBOL")
    result = parse_symbol_master_csv(bad_symbol)
    assert result.symbols == []
    assert result.rows_skipped == 1


def test_invalid_isin_becomes_none_but_row_still_parses():
    bad_isin = VALID_ROW.replace("INE144J01027", "GARBAGE")
    result = parse_symbol_master_csv(bad_isin)
    assert len(result.symbols) == 1
    assert result.symbols[0].isin is None


def test_blank_lines_are_ignored():
    csv_text = f"\n{VALID_ROW}\n\n{NOT_MTF_ROW}\n"
    result = parse_symbol_master_csv(csv_text)
    assert len(result.symbols) == 2
    assert result.rows_seen == 2
