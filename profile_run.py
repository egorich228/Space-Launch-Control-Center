import sys, time, timeit, tracemalloc, cProfile, pstats, io, sqlite3, importlib

SIZES = [1000, 10000, 50000]
PERIOD = ("2026-01-01", "2026-03-31")


def run_scenario(mod_name, fn_name, args_fn, tag, db_suffix=""):
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, fn_name)
    out = open(f"results_{tag}.txt", "w", encoding="utf-8")

    for n in SIZES:
        conn = sqlite3.connect(f"test_{n}{db_suffix}.db")
        args = args_fn(conn)
        out.write(f"\n===== {tag} | n={n} =====\n")

        pr = cProfile.Profile()
        pr.enable()
        res = fn(conn, *args)
        pr.disable()
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats("tottime")
        ps.print_stats(20)
        out.write("-- cProfile (top 20 по tottime) --\n")
        out.write(s.getvalue())
        out.write(f"Строк в результате: {len(res)}\n")

        t = timeit.timeit(lambda: fn(conn, *args), number=10)
        out.write(f"-- timeit: {t/10*1000:.2f} мс/вызов (среднее по 10) --\n")

        tracemalloc.start()
        fn(conn, *args)
        cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        out.write(f"-- tracemalloc: текущая {cur/1024:.1f} КБ, пик {peak/1024:.1f} КБ --\n")

        conn.close()
    out.close()
    print(f"Готово: results_{tag}.txt")


if __name__ == "__main__":
    mod = sys.argv[1]
    tag = sys.argv[2]
    suffix = sys.argv[3] if len(sys.argv) > 3 else ""

    run_scenario(mod, "report_fuel_usage", lambda c: PERIOD, f"fuel_{tag}", suffix)
    run_scenario(mod, "search_launches", lambda c: ("Союз-2.1а", "выполнен"), f"search_{tag}", suffix)
    run_scenario(mod, "report_pad_load", lambda c: PERIOD, f"pad_{tag}", suffix)