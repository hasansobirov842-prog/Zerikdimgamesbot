def init_db():
    restore_backup_if_needed()

    con = connect()
    cur = con.cursor()

    # =========================
    # USERS
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        points REAL DEFAULT 0,
        games INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        referred_by INTEGER,
        last_seen TEXT,
        blocked INTEGER DEFAULT 0,
        referral_rewarded INTEGER DEFAULT 0
    )
    """)

    # Eski DB uchun users migration
    cur.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cur.fetchall()}

    user_migrations = {
        "username": "TEXT",
        "points": "REAL DEFAULT 0",
        "games": "INTEGER DEFAULT 0",
        "wins": "INTEGER DEFAULT 0",
        "referrals": "INTEGER DEFAULT 0",
        "referred_by": "INTEGER",
        "last_seen": "TEXT",
        "blocked": "INTEGER DEFAULT 0",
        "referral_rewarded": "INTEGER DEFAULT 0",
    }

    for column, definition in user_migrations.items():
        if column not in user_columns:
            try:
                cur.execute(
                    f"ALTER TABLE users ADD COLUMN {column} {definition}"
                )
                logger.info(
                    "users.%s ustuni qo‘shildi",
                    column
                )
            except Exception as e:
                logger.error(
                    "users.%s migration xatosi: %s",
                    column,
                    e
                )

    # =========================
    # SPONSORS
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sponsors (
        channel TEXT PRIMARY KEY
    )
    """)

    # =========================
    # TASKS
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT UNIQUE,
        reward REAL DEFAULT 5
    )
    """)

    # ENG MUHIM:
    # Eski zerikdim.db dagi tasks jadvalida
    # channel bo‘lmasa avtomatik qo‘shiladi.
    cur.execute("PRAGMA table_info(tasks)")
    task_columns = {row[1] for row in cur.fetchall()}

    if "channel" not in task_columns:
        try:
            cur.execute(
                "ALTER TABLE tasks ADD COLUMN channel TEXT"
            )
            logger.info(
                "✅ Eski tasks jadvaliga channel ustuni qo‘shildi."
            )
        except Exception as e:
            logger.error(
                "❌ tasks.channel migration xatosi: %s",
                e
            )

    if "reward" not in task_columns:
        try:
            cur.execute(
                "ALTER TABLE tasks ADD COLUMN reward REAL DEFAULT 5"
            )
            logger.info(
                "✅ Eski tasks jadvaliga reward ustuni qo‘shildi."
            )
        except Exception as e:
            logger.error(
                "❌ tasks.reward migration xatosi: %s",
                e
            )

    # Eski task jadvalida url bo‘lgan bo‘lsa,
    # channel bo‘sh tasklarni url orqali to‘ldirishga harakat qilamiz.
    cur.execute("PRAGMA table_info(tasks)")
    task_columns = {row[1] for row in cur.fetchall()}

    if "url" in task_columns:
        try:
            cur.execute("""
            UPDATE tasks
            SET channel =
                CASE
                    WHEN channel IS NULL OR TRIM(channel) = ''
                    THEN
                        CASE
                            WHEN url LIKE 'https://t.me/%'
                            THEN '@' || REPLACE(
                                REPLACE(
                                    REPLACE(url,'https://t.me/',''),
                                    'http://t.me/',''
                                ),
                                '/',''
                            )
                            ELSE channel
                        END
                    ELSE channel
                END
            WHERE channel IS NULL OR TRIM(channel)=''
            """)
        except Exception as e:
            logger.warning(
                "Eski tasklarni migration qilishda xato: %s",
                e
            )

    # =========================
    # TASK CLAIMS
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_claims (
        user_id INTEGER,
        task_id INTEGER,
        claimed_at TEXT,
        PRIMARY KEY(user_id, task_id)
    )
    """)

    # Eski task_claims uchun created_at bo‘lsa ham,
    # yangi kod claimed_at ishlatadi.
    cur.execute("PRAGMA table_info(task_claims)")
    claim_columns = {row[1] for row in cur.fetchall()}

    if "claimed_at" not in claim_columns:
        try:
            cur.execute("""
            ALTER TABLE task_claims
            ADD COLUMN claimed_at TEXT
            """)
        except Exception as e:
            logger.warning(
                "task_claims migration: %s",
                e
            )

    # =========================
    # WITHDRAWALS
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )
    """)

    # Eski withdrawals uchun migration
    cur.execute("PRAGMA table_info(withdrawals)")
    withdrawal_columns = {
        row[1] for row in cur.fetchall()
    }

    withdrawal_migrations = {
        "user_id": "INTEGER",
        "username": "TEXT",
        "amount": "REAL",
        "status": "TEXT DEFAULT 'pending'",
        "created_at": "TEXT",
    }

    for column, definition in withdrawal_migrations.items():
        if column not in withdrawal_columns:
            try:
                cur.execute(
                    f"ALTER TABLE withdrawals ADD COLUMN {column} {definition}"
                )
            except Exception as e:
                logger.warning(
                    "withdrawals.%s migration: %s",
                    column,
                    e
                )

    # =========================
    # BOT STATS
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_stats (
        id INTEGER PRIMARY KEY CHECK(id=1),
        started_at TEXT,
        total_users INTEGER DEFAULT 0
    )
    """)

    # =========================
    # USER STATISTIKA
    # =========================
    current_users = cur.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    row = cur.execute(
        "SELECT total_users FROM bot_stats WHERE id=1"
    ).fetchone()

    if row is None:
        cur.execute("""
        INSERT INTO bot_stats(
            id,
            started_at,
            total_users
        )
        VALUES(1,?,?)
        """, (
            now(),
            current_users
        ))
    else:
        saved_total = int(row[0] or 0)

        # Statistikani hech qachon kamaytirmaymiz.
        if current_users > saved_total:
            cur.execute("""
            UPDATE bot_stats
            SET total_users=?
            WHERE id=1
            """, (
                current_users,
            ))

    # =========================
    # ASOSIY HOMIY
    # =========================
    cur.execute(
        "INSERT OR IGNORE INTO sponsors(channel) VALUES(?)",
        (SPONSOR,)
    )

    # =========================
    # ASOSIY SHART
    # =========================
    # channel ustuni endi mavjud bo‘lganidan keyin
    # bu INSERT xato bermaydi.
    try:
        cur.execute(
            "INSERT OR IGNORE INTO tasks(channel,reward) VALUES(?,?)",
            (
                SPONSOR,
                TASK_REWARD
            )
        )
    except sqlite3.IntegrityError:
        pass

    con.commit()
    con.close()

    logger.info("✅ DATABASE INIT TUGADI")
