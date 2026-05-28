from fastmcp import FastMCP
import aiosqlite
import json
import sqlite3
import os
from datetime import datetime
from typing import Optional

# ── Server setup ──────────────────────────────────────────────────────────────
mcp = FastMCP("Expense Tracker", "1.0.0")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db")
CATEGORIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "categories.json")

print(f"Database path: {DB_PATH}")


# ── Database initialisation (sync once at startup) ────────────────────────────
def _init_db() -> None:
    """Create table and verify write access using sync sqlite3 at startup."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                amount      REAL    NOT NULL,
                category    TEXT    NOT NULL,
                subcategory TEXT    DEFAULT '',
                note        TEXT    DEFAULT '',
                date        TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO expenses(title,amount,category,date,created_at) "
            "VALUES('__init_test__',0,'test','2000-01-01','2000-01-01')"
        )
        conn.execute("DELETE FROM expenses WHERE category='test'")
        conn.commit()


_init_db()
print("✅ Database initialised with write access.")


# ── Async helpers ─────────────────────────────────────────────────────────────

async def _load_categories() -> dict:
    """Read categories.json asynchronously."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: json.load(open(CATEGORIES_PATH))
    )


async def _valid_category_ids() -> list[str]:
    data = await _load_categories()
    return [c["id"] for c in data["categories"]]


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool
async def add_expense(
    title: str,
    amount: float,
    category: str,
    subcategory: Optional[str] = None,
    note: Optional[str] = None,
    date: Optional[str] = None,
) -> str:
    """
    Add a new expense to the tracker.

    Args:
        title       : Short label for the expense (e.g. "Lunch at Subway").
        amount      : Amount spent (positive number).
        category    : Category ID from categories.json (e.g. "food_dining").
        subcategory : Optional subcategory (e.g. "Restaurants").
        note        : Optional extra note or description.
        date        : Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        JSON string with the saved expense details.
    """
    if amount <= 0:
        return json.dumps({"error": "Amount must be a positive number."})

    valid_cats = await _valid_category_ids()
    if category not in valid_cats:
        return json.dumps({
            "error": f"Invalid category '{category}'.",
            "valid_categories": valid_cats,
        })

    expense_date = date or datetime.now().strftime("%Y-%m-%d")
    created_at   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sub  = subcategory or ""
    note = note or ""

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO expenses (title, amount, category, subcategory, note, date, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (title, amount, category, sub, note, expense_date, created_at),
        )
        await db.commit()
        expense_id = cursor.lastrowid

    return json.dumps({
        "success": True,
        "message": f"Expense '{title}' of ₹{amount:.2f} added successfully.",
        "expense": {
            "id": expense_id, "title": title, "amount": amount,
            "category": category, "subcategory": sub, "note": note,
            "date": expense_date, "created_at": created_at,
        },
    }, indent=2)


@mcp.tool
async def get_expenses(
    category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    Retrieve expenses with optional filters.

    Args:
        category   : Filter by category ID (optional).
        start_date : Filter from this date YYYY-MM-DD (optional).
        end_date   : Filter until this date YYYY-MM-DD (optional).
        limit      : Max records to return (default 50).

    Returns:
        JSON string with list of expenses and total amount.
    """
    query  = "SELECT * FROM expenses WHERE 1=1"
    params: list = []

    if category:
        query += " AND category = ?"
        params.append(category)
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)

    query += " ORDER BY date DESC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()

    expenses = [dict(r) for r in rows]
    total    = sum(e["amount"] for e in expenses)

    return json.dumps({
        "count": len(expenses),
        "total": round(total, 2),
        "expenses": expenses,
    }, indent=2)


@mcp.tool
async def delete_expense(expense_id: int) -> str:
    """
    Delete an expense by its ID.

    Args:
        expense_id: The ID of the expense to delete.

    Returns:
        JSON string confirming deletion or an error message.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            return json.dumps({"error": f"No expense found with ID {expense_id}."})

        await db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        await db.commit()

    return json.dumps({
        "success": True,
        "message": f"Expense ID {expense_id} ('{row['title']}') deleted successfully.",
    }, indent=2)


@mcp.tool
async def update_expense(
    expense_id: int,
    title: Optional[str] = None,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    note: Optional[str] = None,
    date: Optional[str] = None,
) -> str:
    """
    Update one or more fields of an existing expense.

    Args:
        expense_id  : ID of the expense to update.
        title       : New title (optional).
        amount      : New amount (optional).
        category    : New category ID (optional).
        subcategory : New subcategory (optional).
        note        : New note (optional).
        date        : New date YYYY-MM-DD (optional).

    Returns:
        JSON string with updated expense details.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            return json.dumps({"error": f"No expense found with ID {expense_id}."})

        updated = dict(row)

        if title       is not None: updated["title"]       = title
        if amount      is not None:
            if amount <= 0:
                return json.dumps({"error": "Amount must be a positive number."})
            updated["amount"] = amount
        if category    is not None:
            valid_cats = await _valid_category_ids()
            if category not in valid_cats:
                return json.dumps({"error": f"Invalid category '{category}'."})
            updated["category"] = category
        if subcategory is not None: updated["subcategory"] = subcategory
        if note        is not None: updated["note"]        = note
        if date        is not None: updated["date"]        = date

        await db.execute(
            """UPDATE expenses
               SET title=?, amount=?, category=?, subcategory=?, note=?, date=?
               WHERE id=?""",
            (
                updated["title"], updated["amount"], updated["category"],
                updated["subcategory"], updated["note"], updated["date"],
                expense_id,
            ),
        )
        await db.commit()

    return json.dumps({
        "success": True,
        "message": f"Expense ID {expense_id} updated successfully.",
        "expense": updated,
    }, indent=2)


@mcp.tool
async def get_monthly_summary(year: int, month: int) -> str:
    """
    Get a spending summary grouped by category for a given month.

    Args:
        year  : The year (e.g. 2025).
        month : The month (1–12).

    Returns:
        JSON string with per-category totals and overall total.
    """
    month_str = f"{year}-{month:02d}"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT category, COUNT(*) as count, SUM(amount) as total
               FROM expenses
               WHERE strftime('%Y-%m', date) = ?
               GROUP BY category ORDER BY total DESC""",
            (month_str,),
        ) as cur:
            rows = await cur.fetchall()

    cat_data    = await _load_categories()
    cat_map     = {c["id"]: c for c in cat_data["categories"]}
    summary, grand_total = [], 0.0

    for row in rows:
        cat_info = cat_map.get(row["category"], {})
        total    = round(row["total"], 2)
        grand_total += total
        summary.append({
            "category_id":   row["category"],
            "category_name": cat_info.get("name", row["category"]),
            "icon":          cat_info.get("icon", ""),
            "transactions":  row["count"],
            "total":         total,
        })

    return json.dumps({
        "period":      month_str,
        "grand_total": round(grand_total, 2),
        "breakdown":   summary,
    }, indent=2)


@mcp.tool
async def get_category_summary() -> str:
    """
    Get all-time total spending grouped by category.

    Returns:
        JSON string with per-category totals.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT category, COUNT(*) as count, SUM(amount) as total
               FROM expenses GROUP BY category ORDER BY total DESC"""
        ) as cur:
            rows = await cur.fetchall()

    cat_data    = await _load_categories()
    cat_map     = {c["id"]: c for c in cat_data["categories"]}
    summary, grand_total = [], 0.0

    for row in rows:
        cat_info = cat_map.get(row["category"], {})
        total    = round(row["total"], 2)
        grand_total += total
        summary.append({
            "category_id":   row["category"],
            "category_name": cat_info.get("name", row["category"]),
            "icon":          cat_info.get("icon", ""),
            "transactions":  row["count"],
            "total":         total,
        })

    return json.dumps({
        "grand_total": round(grand_total, 2),
        "breakdown":   summary,
    }, indent=2)


@mcp.tool
async def list_categories() -> str:
    """
    List all available expense categories and their subcategories.

    Returns:
        JSON string with all categories.
    """
    data = await _load_categories()
    return json.dumps(data, indent=2)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
