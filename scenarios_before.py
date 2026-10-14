import sqlite3, scenarios_before as sb, scenarios_after as sa

PERIOD = ("2024-01-01", "2027-12-31")

for n in (1000, 10000, 50000):
    before = sqlite3.connect(f"test_{n}.db")
    after = sqlite3.connect(f"test_{n}_idx.db")

    r1 = set(sb.report_fuel_usage(before, *PERIOD))
    r2 = set(sa.report_fuel_usage(after, *PERIOD))
    assert r1 == r2, f"fuel mismatch n={n}"

    r1 = set(sb.search_launches(before, "Союз-2.1а", "выполнен"))
    r2 = set(sa.search_launches(after, "Союз-2.1а", "выполнен"))
    assert r1 == r2, f"search mismatch n={n}"

    r1 = sb.report_pad_load(before, *PERIOD)
    r2 = sa.report_pad_load(after, *PERIOD)
    assert sorted(r1) == sorted(r2), f"pad mismatch n={n}: {r1} vs {r2}"

    print(f"n={n}: все три сценария дают идентичный результат ДО и ПОСЛЕ оптимизации — OK")