"""Gold standard question set for the Chinook database (spec §11).

Every gold_sql/gold_answer pair here was computed by actually running the SQL
against db/chinook.db, not copied from the design spec's illustrative
examples -- this DB's invoice dates happen to fall in 2021-2025 rather than
the spec's 2009-2013 examples, so those wouldn't have matched anyway.
tests/unit/test_gold_questions.py re-runs gold_sql on every test collection
and asserts it still equals gold_answer, so this file can't silently drift
from the actual database.
"""

GOLD_QUESTIONS = [
    {
        "question": "What is the total revenue from all invoices?",
        "gold_sql": "SELECT SUM(Total) FROM Invoice",
        "gold_answer": 2328.6,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "Who are the top 5 customers by total spending?",
        "gold_sql": """
            SELECT c.FirstName || ' ' || c.LastName, SUM(i.Total)
            FROM Customer c JOIN Invoice i ON c.CustomerId = i.CustomerId
            GROUP BY c.CustomerId ORDER BY SUM(i.Total) DESC LIMIT 5
        """,
        "gold_answer": [
            ("Helena Holý", 49.62),
            ("Richard Cunningham", 47.62),
            ("Luis Rojas", 46.62),
            ("Ladislav Kovács", 45.62),
            ("Hugh O'Reilly", 45.62),
        ],
        "type": "ranking",
        "requested_n": 5,
    },
    {
        "question": "Show me monthly revenue for 2021",
        "gold_sql": """
            SELECT strftime('%m', InvoiceDate) as month, SUM(Total)
            FROM Invoice WHERE strftime('%Y', InvoiceDate) = '2021'
            GROUP BY month ORDER BY month
        """,
        "type": "trend",
        "min_rows": 12,
    },
    {
        "question": "How many music genres are there?",
        "gold_sql": "SELECT COUNT(*) FROM Genre",
        "gold_answer": 25,
        "type": "fact",
    },
    {
        "question": "Which genre has the most tracks?",
        "gold_sql": """
            SELECT g.Name, COUNT(*) c FROM Track t JOIN Genre g ON t.GenreId = g.GenreId
            GROUP BY g.Name ORDER BY c DESC LIMIT 1
        """,
        "gold_answer": [("Rock", 1297)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many employees are there?",
        "gold_sql": "SELECT COUNT(*) FROM Employee",
        "gold_answer": 8,
        "type": "fact",
    },
    {
        "question": "How many playlists are there?",
        "gold_sql": "SELECT COUNT(*) FROM Playlist",
        "gold_answer": 18,
        "type": "fact",
    },
    {
        "question": "What is the average invoice total?",
        "gold_sql": "SELECT AVG(Total) FROM Invoice",
        "gold_answer": 5.651941747572815,
        "type": "fact",
        "tolerance": 0.001,
    },
    {
        "question": "Which country has the most customers?",
        "gold_sql": """
            SELECT Country, COUNT(*) c FROM Customer GROUP BY Country ORDER BY c DESC LIMIT 1
        """,
        "gold_answer": [("USA", 13)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Does a customer named Helena Holý exist?",
        "gold_sql": "SELECT COUNT(*) FROM Customer WHERE FirstName = 'Helena' AND LastName = 'Holý'",
        "gold_answer": 1,
        "type": "existence",
    },
    {
        "question": "Compare total revenue between 2021 and 2022",
        "gold_sql": """
            SELECT strftime('%Y', InvoiceDate) y, SUM(Total)
            FROM Invoice WHERE strftime('%Y', InvoiceDate) IN ('2021', '2022')
            GROUP BY y
        """,
        "gold_answer": [("2021", 449.46), ("2022", 481.45)],
        "type": "comparison",
    },
    {
        "question": "How many Rock tracks are there?",
        "gold_sql": """
            SELECT COUNT(*) FROM Track t JOIN Genre g ON t.GenreId = g.GenreId
            WHERE g.Name = 'Rock'
        """,
        "gold_answer": 1297,
        "type": "fact",
    },
    {
        "question": "How many tracks are in the catalog in total?",
        "gold_sql": "SELECT COUNT(*) FROM Track",
        "gold_answer": 3503,
        "type": "fact",
    },
    {
        "question": "What is the longest track by duration?",
        "gold_sql": "SELECT Name, Milliseconds FROM Track ORDER BY Milliseconds DESC LIMIT 1",
        "gold_answer": [("Occupation / Precipice", 5286953)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many media types are there?",
        "gold_sql": "SELECT COUNT(*) FROM MediaType",
        "gold_answer": 5,
        "type": "fact",
    },
    {
        "question": "Which artist has generated the most revenue?",
        "gold_sql": """
            SELECT ar.Name, SUM(il.UnitPrice * il.Quantity) rev
            FROM InvoiceLine il JOIN Track t ON il.TrackId = t.TrackId
            JOIN Album al ON t.AlbumId = al.AlbumId JOIN Artist ar ON al.ArtistId = ar.ArtistId
            GROUP BY ar.ArtistId ORDER BY rev DESC LIMIT 1
        """,
        "gold_answer": [("Iron Maiden", 138.6)],
        "type": "ranking",
        "requested_n": 1,
    },
]
