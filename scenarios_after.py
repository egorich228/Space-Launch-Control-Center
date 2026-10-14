def report_fuel_usage(conn, a, b):
    sql = ("SELECT u.batch_id,b.fuel,u.launch_id,u.volume,u.dt FROM usage u "
           "JOIN batches b ON b.id=u.batch_id WHERE date(u.dt) BETWEEN ? AND ? ORDER BY u.batch_id")
    return conn.execute(sql, (a, b)).fetchall()


def search_launches(conn, rocket_type, status):
    sql = ("SELECT l.id, r.type, pl.type, p.name, l.start_time, l.status "
           "FROM launches l JOIN rockets r ON r.id=l.rocket_id "
           "JOIN payloads pl ON pl.id=l.payload_id JOIN pads p ON p.id=l.pad_id "
           "WHERE r.type=? AND l.status=?")
    return conn.execute(sql, (rocket_type, status)).fetchall()


def report_pad_load(conn, a, b):
    sql = ("SELECT p.name,"
           "SUM(CASE WHEN l.status!='отменен' AND date(l.start_time) BETWEEN :a AND :b THEN 1 ELSE 0 END),"
           "SUM(CASE WHEN l.status='выполнен' AND date(l.start_time) BETWEEN :a AND :b THEN 1 ELSE 0 END),"
           "(SELECT COALESCE(SUM(MAX(0,julianday(MIN(m.d2,:b))-julianday(MAX(m.d1,:a))+1)),0) FROM maintenance m WHERE m.pad_id=p.id) "
           "FROM pads p LEFT JOIN launches l ON l.pad_id=p.id "
           "GROUP BY p.id ORDER BY p.id")
    return conn.execute(sql, {"a": a, "b": b}).fetchall()


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_usage_date ON usage(date(dt));
CREATE INDEX IF NOT EXISTS idx_launches_rocket ON launches(rocket_id);
CREATE INDEX IF NOT EXISTS idx_launches_status ON launches(status);
CREATE INDEX IF NOT EXISTS idx_launches_pad ON launches(pad_id);
CREATE INDEX IF NOT EXISTS idx_launches_startdate ON launches(date(start_time));
"""