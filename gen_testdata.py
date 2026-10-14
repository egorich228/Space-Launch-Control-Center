import sys, os, random, datetime
from schema import connect

random.seed(42)

ROCKET_TYPES = ["Союз-2.1а", "Ангара-А5", "Протон-М", "Старт-1"]
ORBITS = ["ГСО", "ССО", "НОО", "ВЭО"]
PAYLOAD_TYPES = ["Спутник связи", "Метеоспутник", "Грузовой корабль", "Научный модуль"]
PADS = ["Площадка 31", "Площадка 1С", "Площадка 81", "Площадка 17"]
STATUSES = ["запланирован", "подготовка", "готов", "выполнен", "перенесен", "отменен"]
STATUS_W = [10, 10, 5, 65, 5, 5]
FUELS = ["Горючее", "Окислитель"]


def rand_dt(start_year=2024, end_year=2027):
    start = datetime.datetime(start_year, 1, 1)
    end = datetime.datetime(end_year, 12, 31)
    delta = end - start
    d = start + datetime.timedelta(seconds=random.randint(0, int(delta.total_seconds())))
    return d


def generate(n_launches, out_path):
    if os.path.exists(out_path):
        os.remove(out_path)
    conn = connect(out_path)
    cur = conn.cursor()

    cur.executemany("INSERT INTO rockets(id,type,specs) VALUES(?,?,?)",
                     [(i + 1, t, "") for i, t in enumerate(ROCKET_TYPES)])
    cur.executemany("INSERT INTO pads(id,name) VALUES(?,?)",
                     [(i + 1, n) for i, n in enumerate(PADS)])

    n_payloads = max(50, n_launches // 10)
    cur.executemany("INSERT INTO payloads(id,type,mass,orbit) VALUES(?,?,?,?)",
                     [(i + 1, random.choice(PAYLOAD_TYPES), round(random.uniform(200, 8000), 1), random.choice(ORBITS))
                      for i in range(n_payloads)])

    n_batches = max(20, n_launches // 40)
    batches = []
    for i in range(n_batches):
        vol = round(random.uniform(2000, 20000), 1)
        expiry = (rand_dt(2024, 2028)).strftime("%Y-%m-%d")
        batches.append((i + 1, random.choice(FUELS), vol, vol, expiry))
    cur.executemany("INSERT INTO batches(id,fuel,volume,remaining,expiry) VALUES(?,?,?,?,?)", batches)

    maint = []
    mid = 1
    for pad_id in range(1, len(PADS) + 1):
        for _ in range(max(3, n_launches // 2000)):
            d1 = rand_dt(2024, 2027)
            d2 = d1 + datetime.timedelta(days=random.randint(1, 10))
            maint.append((mid, pad_id, d1.strftime("%Y-%m-%d"), d2.strftime("%Y-%m-%d"), "Осмотр"))
            mid += 1
    cur.executemany("INSERT INTO maintenance(id,pad_id,d1,d2,kind) VALUES(?,?,?,?,?)", maint)

    launches = []
    usage_rows = []
    uid = 1
    for i in range(1, n_launches + 1):
        rocket_id = random.randint(1, len(ROCKET_TYPES))
        payload_id = random.randint(1, n_payloads)
        pad_id = random.randint(1, len(PADS))
        status = random.choices(STATUSES, weights=STATUS_W, k=1)[0]
        start = rand_dt(2024, 2027).strftime("%Y-%m-%d %H:%M")
        launches.append((i, rocket_id, payload_id, random.choice(ORBITS), pad_id, start, status))
        if random.random() < 0.7:
            for _ in range(random.randint(1, 2)):
                usage_rows.append((uid, random.randint(1, n_batches), i,
                                    round(random.uniform(50, 2000), 1),
                                    rand_dt(2024, 2027).strftime("%Y-%m-%d %H:%M")))
                uid += 1
    cur.executemany("INSERT INTO launches(id,rocket_id,payload_id,orbit,pad_id,start_time,status) VALUES(?,?,?,?,?,?,?)", launches)
    cur.executemany("INSERT INTO usage(id,batch_id,launch_id,volume,dt) VALUES(?,?,?,?,?)", usage_rows)

    conn.commit()
    conn.close()
    print(f"{out_path}: {n_launches} пусков, {len(usage_rows)} списаний топлива, {len(maint)} интервалов обслуживания")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    out = sys.argv[2] if len(sys.argv) > 2 else f"test_{n}.db"
    generate(n, out)