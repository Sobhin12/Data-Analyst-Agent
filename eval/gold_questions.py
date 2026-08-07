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
    # --- Harder questions below: HAVING on an aggregate, anti-joins, a
    # correlated subquery, rank position (not just top-1), a self-join, and
    # a percentage -- patterns a naive text-to-SQL agent tends to get wrong
    # (e.g. filtering an aggregate with WHERE instead of HAVING, or forgetting
    # LEFT JOIN ... IS NULL is how you express "never").
    {
        "question": "Which genres generated more than $500 in total revenue?",
        "gold_sql": """
            SELECT g.Name, ROUND(SUM(il.UnitPrice * il.Quantity), 2) rev
            FROM InvoiceLine il JOIN Track t ON il.TrackId = t.TrackId
            JOIN Genre g ON t.GenreId = g.GenreId
            GROUP BY g.GenreId HAVING rev > 500 ORDER BY rev DESC
        """,
        "gold_answer": [("Rock", 826.65)],
        "type": "fact",
    },
    {
        "question": "How many customers have never made a purchase?",
        "gold_sql": """
            SELECT COUNT(*) FROM Customer c
            LEFT JOIN Invoice i ON c.CustomerId = i.CustomerId
            WHERE i.InvoiceId IS NULL
        """,
        "gold_answer": 0,
        "type": "existence",
    },
    {
        "question": "How many customers have spent more than the average customer?",
        "gold_sql": """
            SELECT COUNT(*) FROM (
                SELECT CustomerId, SUM(Total) tot FROM Invoice GROUP BY CustomerId
            ) sub
            WHERE tot > (SELECT AVG(tot) FROM (SELECT SUM(Total) tot FROM Invoice GROUP BY CustomerId))
        """,
        "gold_answer": 22,
        "type": "fact",
    },
    {
        "question": "Who is the second highest-spending customer?",
        "gold_sql": """
            SELECT c.FirstName || ' ' || c.LastName, ROUND(SUM(i.Total), 2)
            FROM Customer c JOIN Invoice i ON c.CustomerId = i.CustomerId
            GROUP BY c.CustomerId ORDER BY SUM(i.Total) DESC LIMIT 1 OFFSET 1
        """,
        "gold_answer": [("Richard Cunningham", 47.62)],
        "type": "ranking",
    },
    {
        "question": "How many employees report directly to Nancy Edwards?",
        "gold_sql": """
            SELECT COUNT(*) FROM Employee e
            JOIN Employee m ON e.ReportsTo = m.EmployeeId
            WHERE m.FirstName = 'Nancy' AND m.LastName = 'Edwards'
        """,
        "gold_answer": 3,
        "type": "fact",
    },
    {
        "question": "What percentage of tracks are in the Rock genre?",
        "gold_sql": """
            SELECT ROUND(100.0 * SUM(CASE WHEN g.Name = 'Rock' THEN 1 ELSE 0 END) / COUNT(*), 2)
            FROM Track t LEFT JOIN Genre g ON t.GenreId = g.GenreId
        """,
        "gold_answer": 37.03,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many playlists contain at least one track by Iron Maiden?",
        "gold_sql": """
            SELECT COUNT(DISTINCT pt.PlaylistId) FROM PlaylistTrack pt
            JOIN Track t ON pt.TrackId = t.TrackId
            JOIN Album al ON t.AlbumId = al.AlbumId
            JOIN Artist ar ON al.ArtistId = ar.ArtistId
            WHERE ar.Name = 'Iron Maiden'
        """,
        "gold_answer": 4,
        "type": "fact",
    },
    {
        "question": "Which genre has the fewest tracks?",
        "gold_sql": """
            SELECT g.Name, COUNT(*) c FROM Track t JOIN Genre g ON t.GenreId = g.GenreId
            GROUP BY g.GenreId ORDER BY c ASC LIMIT 1
        """,
        "gold_answer": [("Opera", 1)],
        "type": "ranking",
        "requested_n": 1,
    },
    # --- 100 additional questions: cross-table analysis and harder SQL
    # patterns (multi-way joins, correlated subqueries, self-joins, anti-joins,
    # percentages, rank position, ties) meant to stress-test the agent beyond
    # the straightforward single-table facts above. Computed the same way as
    # everything else in this file -- gold_sql actually run against
    # db/chinook.db, not guessed.
    {
        "question": "How many tracks are not included in any playlist?",
        "gold_sql": """
            SELECT COUNT(*) FROM Track WHERE TrackId NOT IN (SELECT DISTINCT TrackId FROM PlaylistTrack)
        """,
        "gold_answer": 0,
        "type": "fact",
    },
    {
        "question": "Which artist has released the most albums?",
        "gold_sql": """
            SELECT ar.Name, COUNT(*) c FROM Album al JOIN Artist ar ON al.ArtistId=ar.ArtistId GROUP BY ar.ArtistId ORDER BY c DESC, ar.Name LIMIT 1
        """,
        "gold_answer": [("Iron Maiden", 21)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many artists have released more than 5 albums?",
        "gold_sql": "SELECT COUNT(*) FROM (SELECT ArtistId FROM Album GROUP BY ArtistId HAVING COUNT(*) > 5)",
        "gold_answer": 6,
        "type": "fact",
    },
    {
        "question": "What is the average number of tracks per album?",
        "gold_sql": "SELECT ROUND(AVG(cnt),2) FROM (SELECT COUNT(*) cnt FROM Track GROUP BY AlbumId)",
        "gold_answer": 10.1,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "Which album has the most tracks?",
        "gold_sql": """
            SELECT al.Title, COUNT(*) c FROM Track t JOIN Album al ON t.AlbumId=al.AlbumId GROUP BY al.AlbumId ORDER BY c DESC, al.Title LIMIT 1
        """,
        "gold_answer": [("Greatest Hits", 57)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many albums contain only a single track?",
        "gold_sql": "SELECT COUNT(*) FROM (SELECT AlbumId FROM Track GROUP BY AlbumId HAVING COUNT(*)=1)",
        "gold_answer": 82,
        "type": "fact",
    },
    {
        "question": "What is the total duration of all tracks in the catalog, in minutes?",
        "gold_sql": "SELECT ROUND(SUM(Milliseconds)/60000.0,2) FROM Track",
        "gold_answer": 22979.63,
        "type": "fact",
        "tolerance": 0.5,
    },
    {
        "question": "What is the average track duration in seconds?",
        "gold_sql": "SELECT ROUND(AVG(Milliseconds)/1000.0,2) FROM Track",
        "gold_answer": 393.6,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "Which genre has the highest average track duration, in milliseconds?",
        "gold_sql": """
            SELECT g.Name, ROUND(AVG(t.Milliseconds),2) avgd FROM Track t JOIN Genre g ON t.GenreId=g.GenreId GROUP BY g.GenreId ORDER BY avgd DESC LIMIT 1
        """,
        "gold_answer": [("Sci Fi & Fantasy", 2911783.04)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Which genre has the shortest average track duration, in milliseconds?",
        "gold_sql": """
            SELECT g.Name, ROUND(AVG(t.Milliseconds),2) avgd FROM Track t JOIN Genre g ON t.GenreId=g.GenreId GROUP BY g.GenreId ORDER BY avgd ASC LIMIT 1
        """,
        "gold_answer": [("Rock And Roll", 134643.5)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Which media type is used by the most tracks?",
        "gold_sql": """
            SELECT mt.Name, COUNT(*) c FROM Track t JOIN MediaType mt ON t.MediaTypeId=mt.MediaTypeId GROUP BY mt.MediaTypeId ORDER BY c DESC LIMIT 1
        """,
        "gold_answer": [("MPEG audio file", 3034)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many distinct composers are credited in the catalog?",
        "gold_sql": "SELECT COUNT(DISTINCT Composer) FROM Track WHERE Composer IS NOT NULL",
        "gold_answer": 853,
        "type": "fact",
    },
    {
        "question": "Which composer has written the most tracks?",
        "gold_sql": """
            SELECT Composer, COUNT(*) c FROM Track WHERE Composer IS NOT NULL GROUP BY Composer ORDER BY c DESC, Composer LIMIT 1
        """,
        "gold_answer": [("Steve Harris", 80)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many tracks have no composer listed?",
        "gold_sql": "SELECT COUNT(*) FROM Track WHERE Composer IS NULL",
        "gold_answer": 977,
        "type": "fact",
    },
    {
        "question": "What is the price of the most expensive track in the catalog?",
        "gold_sql": "SELECT MAX(UnitPrice) FROM Track",
        "gold_answer": 1.99,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many distinct track prices exist in the catalog?",
        "gold_sql": "SELECT COUNT(DISTINCT UnitPrice) FROM Track",
        "gold_answer": 2,
        "type": "fact",
    },
    {
        "question": "Which country has generated the highest total revenue?",
        "gold_sql": """
            SELECT BillingCountry, ROUND(SUM(Total),2) rev FROM Invoice GROUP BY BillingCountry ORDER BY rev DESC LIMIT 1
        """,
        "gold_answer": [("USA", 523.06)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Which country has generated the lowest total revenue?",
        "gold_sql": """
            SELECT BillingCountry, ROUND(SUM(Total),2) rev FROM Invoice GROUP BY BillingCountry ORDER BY rev ASC, BillingCountry LIMIT 1
        """,
        "gold_answer": [("Argentina", 37.62)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many countries have generated more than $100 in total revenue?",
        "gold_sql": """
            SELECT COUNT(*) FROM (SELECT BillingCountry FROM Invoice GROUP BY BillingCountry HAVING SUM(Total) > 100)
        """,
        "gold_answer": 6,
        "type": "fact",
    },
    {
        "question": "What is the average invoice total for customers billed in the USA?",
        "gold_sql": "SELECT ROUND(AVG(Total),2) FROM Invoice WHERE BillingCountry='USA'",
        "gold_answer": 5.75,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "Which city has the most customers?",
        "gold_sql": "SELECT City, COUNT(*) c FROM Customer GROUP BY City ORDER BY c DESC, City LIMIT 1",
        "gold_answer": [("Berlin", 2)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Which sales support employee supports the most customers?",
        "gold_sql": """
            SELECT e.FirstName || ' ' || e.LastName, COUNT(*) c FROM Customer cu JOIN Employee e ON cu.SupportRepId=e.EmployeeId GROUP BY e.EmployeeId ORDER BY c DESC LIMIT 1
        """,
        "gold_answer": [("Jane Peacock", 21)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Which sales support employee has generated the most revenue through their assigned customers?",
        "gold_sql": """
            SELECT e.FirstName || ' ' || e.LastName, ROUND(SUM(i.Total),2) rev FROM Employee e JOIN Customer cu ON cu.SupportRepId=e.EmployeeId JOIN Invoice i ON i.CustomerId=cu.CustomerId GROUP BY e.EmployeeId ORDER BY rev DESC LIMIT 1
        """,
        "gold_answer": [("Jane Peacock", 833.04)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many employees are assigned as a support rep to at least one customer?",
        "gold_sql": "SELECT COUNT(DISTINCT SupportRepId) FROM Customer",
        "gold_answer": 3,
        "type": "fact",
    },
    {
        "question": "Which employee has the most direct reports?",
        "gold_sql": """
            SELECT m.FirstName || ' ' || m.LastName, COUNT(*) c FROM Employee e JOIN Employee m ON e.ReportsTo=m.EmployeeId GROUP BY m.EmployeeId ORDER BY c DESC LIMIT 1
        """,
        "gold_answer": [("Nancy Edwards", 3)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many employees have no manager (report to no one)?",
        "gold_sql": "SELECT COUNT(*) FROM Employee WHERE ReportsTo IS NULL",
        "gold_answer": 1,
        "type": "fact",
    },
    {
        "question": "What was the average age of employees at the time they were hired?",
        "gold_sql": "SELECT ROUND(AVG((julianday(HireDate) - julianday(BirthDate))/365.25),1) FROM Employee",
        "gold_answer": 38.3,
        "type": "fact",
        "tolerance": 0.1,
    },
    {
        "question": "Who is the youngest employee?",
        "gold_sql": "SELECT FirstName || ' ' || LastName FROM Employee ORDER BY BirthDate DESC LIMIT 1",
        "gold_answer": "Jane Peacock",
        "type": "fact",
    },
    {
        "question": "Who is the oldest employee?",
        "gold_sql": "SELECT FirstName || ' ' || LastName FROM Employee ORDER BY BirthDate ASC LIMIT 1",
        "gold_answer": "Margaret Park",
        "type": "fact",
    },
    {
        "question": "Who was the first employee hired?",
        "gold_sql": "SELECT FirstName || ' ' || LastName FROM Employee ORDER BY HireDate ASC LIMIT 1",
        "gold_answer": "Jane Peacock",
        "type": "fact",
    },
    {
        "question": "Who was the most recently hired employee?",
        "gold_sql": "SELECT FirstName || ' ' || LastName FROM Employee ORDER BY HireDate DESC LIMIT 1",
        "gold_answer": "Laura Callahan",
        "type": "fact",
    },
    {
        "question": "How many distinct job titles exist among employees?",
        "gold_sql": "SELECT COUNT(DISTINCT Title) FROM Employee",
        "gold_answer": 5,
        "type": "fact",
    },
    {
        "question": "What is the most common job title among employees?",
        "gold_sql": "SELECT Title, COUNT(*) c FROM Employee GROUP BY Title ORDER BY c DESC, Title LIMIT 1",
        "gold_answer": [("Sales Support Agent", 3)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many tracks are longer than 5 minutes?",
        "gold_sql": "SELECT COUNT(*) FROM Track WHERE Milliseconds > 300000",
        "gold_answer": 1069,
        "type": "fact",
    },
    {
        "question": "How many tracks are shorter than 1 minute?",
        "gold_sql": "SELECT COUNT(*) FROM Track WHERE Milliseconds < 60000",
        "gold_answer": 27,
        "type": "fact",
    },
    {
        "question": "Which album has the longest total duration?",
        "gold_sql": """
            SELECT al.Title, ROUND(SUM(t.Milliseconds)/60000.0,2) dur FROM Track t JOIN Album al ON t.AlbumId=al.AlbumId GROUP BY al.AlbumId ORDER BY dur DESC LIMIT 1
        """,
        "gold_answer": [("Lost, Season 3", 1177.76)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Which playlist has the most tracks?",
        "gold_sql": """
            SELECT p.Name, COUNT(*) c FROM PlaylistTrack pt JOIN Playlist p ON pt.PlaylistId=p.PlaylistId GROUP BY p.PlaylistId ORDER BY c DESC LIMIT 1
        """,
        "gold_answer": [("Music", 3290)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many playlists have no tracks at all?",
        "gold_sql": """
            SELECT COUNT(*) FROM Playlist p LEFT JOIN PlaylistTrack pt ON p.PlaylistId=pt.PlaylistId WHERE pt.TrackId IS NULL
        """,
        "gold_answer": 4,
        "type": "fact",
    },
    {
        "question": "Which genre appears in the most playlists?",
        "gold_sql": """
            SELECT g.Name, COUNT(DISTINCT pt.PlaylistId) c FROM PlaylistTrack pt JOIN Track t ON pt.TrackId=t.TrackId JOIN Genre g ON t.GenreId=g.GenreId GROUP BY g.GenreId ORDER BY c DESC LIMIT 1
        """,
        "gold_answer": [("Classical", 7)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many unique artists are represented across all playlists?",
        "gold_sql": """
            SELECT COUNT(DISTINCT ar.ArtistId) FROM PlaylistTrack pt JOIN Track t ON pt.TrackId=t.TrackId JOIN Album al ON t.AlbumId=al.AlbumId JOIN Artist ar ON al.ArtistId=ar.ArtistId
        """,
        "gold_answer": 204,
        "type": "fact",
    },
    {
        "question": "Which artist appears in the most playlists?",
        "gold_sql": """
            SELECT ar.Name, COUNT(DISTINCT pt.PlaylistId) c FROM PlaylistTrack pt JOIN Track t ON pt.TrackId=t.TrackId JOIN Album al ON t.AlbumId=al.AlbumId JOIN Artist ar ON al.ArtistId=ar.ArtistId GROUP BY ar.ArtistId ORDER BY c DESC LIMIT 1
        """,
        "gold_answer": [("Eugene Ormandy", 7)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "What is the total revenue generated from Rock genre tracks?",
        "gold_sql": """
            SELECT ROUND(SUM(il.UnitPrice*il.Quantity),2) FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId JOIN Genre g ON t.GenreId=g.GenreId WHERE g.Name='Rock'
        """,
        "gold_answer": 826.65,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "What percentage of total revenue comes from the Rock genre?",
        "gold_sql": """
            SELECT ROUND(100.0 * SUM(CASE WHEN g.Name='Rock' THEN il.UnitPrice*il.Quantity ELSE 0 END) / SUM(il.UnitPrice*il.Quantity),2) FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId JOIN Genre g ON t.GenreId=g.GenreId
        """,
        "gold_answer": 35.5,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many genres have never generated any revenue?",
        "gold_sql": """
            SELECT COUNT(*) FROM Genre g WHERE g.GenreId NOT IN (SELECT DISTINCT t.GenreId FROM Track t JOIN InvoiceLine il ON t.TrackId=il.TrackId WHERE t.GenreId IS NOT NULL)
        """,
        "gold_answer": 1,
        "type": "fact",
    },
    {
        "question": "How many tracks have never been purchased?",
        "gold_sql": "SELECT COUNT(*) FROM Track WHERE TrackId NOT IN (SELECT DISTINCT TrackId FROM InvoiceLine)",
        "gold_answer": 1519,
        "type": "fact",
    },
    {
        "question": "Which track has generated the most revenue?",
        "gold_sql": """
            SELECT t.Name, ROUND(SUM(il.UnitPrice*il.Quantity),2) rev FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId GROUP BY t.TrackId ORDER BY rev DESC, t.Name LIMIT 1
        """,
        "gold_answer": [("Gay Witch Hunt", 3.98)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Which track has sold the highest total quantity?",
        "gold_sql": """
            SELECT t.Name, SUM(il.Quantity) q FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId GROUP BY t.TrackId ORDER BY q DESC, t.Name LIMIT 1
        """,
        "gold_answer": [("A Cor Do Sol", 2)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "What is the average number of line items per invoice?",
        "gold_sql": "SELECT ROUND(AVG(cnt),2) FROM (SELECT COUNT(*) cnt FROM InvoiceLine GROUP BY InvoiceId)",
        "gold_answer": 5.44,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "What is the largest number of line items in a single invoice?",
        "gold_sql": "SELECT MAX(cnt) FROM (SELECT COUNT(*) cnt FROM InvoiceLine GROUP BY InvoiceId)",
        "gold_answer": 14,
        "type": "fact",
    },
    {
        "question": "What is the highest total value of a single invoice?",
        "gold_sql": "SELECT MAX(Total) FROM Invoice",
        "gold_answer": 25.86,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many customers are from Canada?",
        "gold_sql": "SELECT COUNT(*) FROM Customer WHERE Country='Canada'",
        "gold_answer": 8,
        "type": "fact",
    },
    {
        "question": "What is the total revenue from customers in Canada?",
        "gold_sql": """
            SELECT ROUND(SUM(i.Total),2) FROM Invoice i JOIN Customer c ON i.CustomerId=c.CustomerId WHERE c.Country='Canada'
        """,
        "gold_answer": 303.96,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "What is the average revenue per customer in the USA?",
        "gold_sql": """
            SELECT ROUND(SUM(i.Total)*1.0/COUNT(DISTINCT c.CustomerId),2) FROM Invoice i JOIN Customer c ON i.CustomerId=c.CustomerId WHERE c.Country='USA'
        """,
        "gold_answer": 40.24,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "Which customer has made the most separate purchases (invoices)?",
        "gold_sql": """
            SELECT c.FirstName || ' ' || c.LastName, COUNT(*) c2 FROM Invoice i JOIN Customer c ON i.CustomerId=c.CustomerId GROUP BY c.CustomerId ORDER BY c2 DESC, c.FirstName LIMIT 1
        """,
        "gold_answer": [("Aaron Mitchell", 7)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "What is the average number of invoices per customer?",
        "gold_sql": "SELECT ROUND(COUNT(*)*1.0/COUNT(DISTINCT CustomerId),2) FROM Invoice",
        "gold_answer": 6.98,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many customers have made only a single purchase?",
        "gold_sql": """
            SELECT COUNT(*) FROM (SELECT CustomerId FROM Invoice GROUP BY CustomerId HAVING COUNT(*)=1)
        """,
        "gold_answer": 0,
        "type": "fact",
    },
    {
        "question": "Which artist has the most tracks in the catalog?",
        "gold_sql": """
            SELECT ar.Name, COUNT(*) c FROM Track t JOIN Album al ON t.AlbumId=al.AlbumId JOIN Artist ar ON al.ArtistId=ar.ArtistId GROUP BY ar.ArtistId ORDER BY c DESC, ar.Name LIMIT 1
        """,
        "gold_answer": [("Iron Maiden", 213)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many artists have no albums in the catalog?",
        "gold_sql": "SELECT COUNT(*) FROM Artist WHERE ArtistId NOT IN (SELECT DISTINCT ArtistId FROM Album)",
        "gold_answer": 71,
        "type": "fact",
    },
    {
        "question": "How many artists have never generated any revenue?",
        "gold_sql": """
            SELECT COUNT(*) FROM Artist ar WHERE ar.ArtistId NOT IN (SELECT DISTINCT al.ArtistId FROM Album al JOIN Track t ON t.AlbumId=al.AlbumId JOIN InvoiceLine il ON il.TrackId=t.TrackId)
        """,
        "gold_answer": 110,
        "type": "fact",
    },
    {
        "question": "What percentage of artists have generated at least some revenue?",
        "gold_sql": """
            SELECT ROUND(100.0 * COUNT(DISTINCT al.ArtistId) / (SELECT COUNT(*) FROM Artist), 2) FROM Album al JOIN Track t ON t.AlbumId=al.AlbumId JOIN InvoiceLine il ON il.TrackId=t.TrackId
        """,
        "gold_answer": 60.0,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "Compare the total number of tracks in the Rock genre versus the Jazz genre.",
        "gold_sql": """
            SELECT g.Name, COUNT(*) FROM Track t JOIN Genre g ON t.GenreId=g.GenreId WHERE g.Name IN ('Rock','Jazz') GROUP BY g.Name ORDER BY g.Name
        """,
        "gold_answer": [("Jazz", 130), ("Rock", 1297)],
        "type": "comparison",
    },
    {
        "question": "Compare total revenue generated in the USA versus Canada.",
        "gold_sql": """
            SELECT BillingCountry, ROUND(SUM(Total),2) FROM Invoice WHERE BillingCountry IN ('USA','Canada') GROUP BY BillingCountry ORDER BY BillingCountry
        """,
        "gold_answer": [("Canada", 303.96), ("USA", 523.06)],
        "type": "comparison",
    },
    {
        "question": "Compare the number of customers in the USA versus Germany.",
        "gold_sql": """
            SELECT Country, COUNT(*) FROM Customer WHERE Country IN ('USA','Germany') GROUP BY Country ORDER BY Country
        """,
        "gold_answer": [("Germany", 4), ("USA", 13)],
        "type": "comparison",
    },
    {
        "question": "Show total revenue by quarter for 2021.",
        "gold_sql": """
            SELECT ((CAST(strftime('%m',InvoiceDate) AS INT)-1)/3)+1 q, ROUND(SUM(Total),2) FROM Invoice WHERE strftime('%Y',InvoiceDate)='2021' GROUP BY q ORDER BY q
        """,
        "type": "trend",
        "min_rows": 4,
    },
    {
        "question": "What was the busiest month across the entire dataset, by number of invoices?",
        "gold_sql": """
            SELECT strftime('%Y-%m', InvoiceDate) ym, COUNT(*) c FROM Invoice GROUP BY ym ORDER BY c DESC, ym LIMIT 1
        """,
        "gold_answer": [("2021-02", 7)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Which year had the highest total revenue?",
        "gold_sql": """
            SELECT strftime('%Y',InvoiceDate) y, ROUND(SUM(Total),2) rev FROM Invoice GROUP BY y ORDER BY rev DESC LIMIT 1
        """,
        "gold_answer": [("2022", 481.45)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "What was the total revenue in the first quarter of 2021 (January to March)?",
        "gold_sql": """
            SELECT ROUND(SUM(Total),2) FROM Invoice WHERE InvoiceDate >= '2021-01-01' AND InvoiceDate < '2021-04-01'
        """,
        "gold_answer": 110.88,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many invoices were issued on a weekend?",
        "gold_sql": "SELECT COUNT(*) FROM Invoice WHERE strftime('%w',InvoiceDate) IN ('0','6')",
        "gold_answer": 117,
        "type": "fact",
    },
    {
        "question": "What is the average invoice total for invoices billed to Germany?",
        "gold_sql": "SELECT ROUND(AVG(Total),2) FROM Invoice WHERE BillingCountry='Germany'",
        "gold_answer": 5.59,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many distinct billing cities appear across all invoices?",
        "gold_sql": "SELECT COUNT(DISTINCT BillingCity) FROM Invoice",
        "gold_answer": 53,
        "type": "fact",
    },
    {
        "question": "Which billing city has generated the highest total revenue?",
        "gold_sql": """
            SELECT BillingCity, ROUND(SUM(Total),2) rev FROM Invoice GROUP BY BillingCity ORDER BY rev DESC LIMIT 1
        """,
        "gold_answer": [("Prague", 90.24)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "What percentage of all invoices come from customers billed in the USA?",
        "gold_sql": """
            SELECT ROUND(100.0*SUM(CASE WHEN BillingCountry='USA' THEN 1 ELSE 0 END)/COUNT(*),2) FROM Invoice
        """,
        "gold_answer": 22.09,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many tracks belong to albums by artists whose name starts with the letter A?",
        "gold_sql": """
            SELECT COUNT(*) FROM Track t JOIN Album al ON t.AlbumId=al.AlbumId JOIN Artist ar ON al.ArtistId=ar.ArtistId WHERE ar.Name LIKE 'A%'
        """,
        "gold_answer": 178,
        "type": "fact",
    },
    {
        "question": "How many artists have a name containing the word 'The'?",
        "gold_sql": "SELECT COUNT(*) FROM Artist WHERE Name LIKE '%The%'",
        "gold_answer": 24,
        "type": "fact",
    },
    {
        "question": "Which genre has the highest average track price?",
        "gold_sql": """
            SELECT g.Name, ROUND(AVG(t.UnitPrice),2) avgp FROM Track t JOIN Genre g ON t.GenreId=g.GenreId GROUP BY g.GenreId ORDER BY avgp DESC, g.Name LIMIT 1
        """,
        "gold_answer": [("Comedy", 1.99)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many distinct genres are represented among the top 10 highest-grossing tracks?",
        "gold_sql": """
            SELECT COUNT(DISTINCT t.GenreId) FROM (SELECT il.TrackId, SUM(il.UnitPrice*il.Quantity) rev FROM InvoiceLine il GROUP BY il.TrackId ORDER BY rev DESC LIMIT 10) top JOIN Track t ON top.TrackId=t.TrackId
        """,
        "gold_answer": 4,
        "type": "fact",
    },
    {
        "question": "Which genre sold the highest total quantity of tracks (not revenue)?",
        "gold_sql": """
            SELECT g.Name, SUM(il.Quantity) q FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId JOIN Genre g ON t.GenreId=g.GenreId GROUP BY g.GenreId ORDER BY q DESC LIMIT 1
        """,
        "gold_answer": [("Rock", 835)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many customers have spent more than $40 in total?",
        "gold_sql": """
            SELECT COUNT(*) FROM (SELECT CustomerId FROM Invoice GROUP BY CustomerId HAVING SUM(Total) > 40)
        """,
        "gold_answer": 14,
        "type": "fact",
    },
    {
        "question": "Which 3 customers have spent the least, among those who made at least one purchase?",
        "gold_sql": """
            SELECT c.FirstName || ' ' || c.LastName, ROUND(SUM(i.Total),2) tot FROM Customer c JOIN Invoice i ON c.CustomerId=i.CustomerId GROUP BY c.CustomerId ORDER BY tot ASC, c.FirstName LIMIT 3
        """,
        "gold_answer": [("Puja Srivastava", 36.64), ("Aaron Mitchell", 37.62), ("Alexandre Rocha", 37.62)],
        "type": "ranking",
        "requested_n": 3,
    },
    {
        "question": "What is the combined total revenue of the top 3 highest-spending customers?",
        "gold_sql": """
            SELECT ROUND(SUM(tot),2) FROM (SELECT SUM(Total) tot FROM Invoice GROUP BY CustomerId ORDER BY tot DESC LIMIT 3)
        """,
        "gold_answer": 143.86,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "What percentage of total revenue comes from the top 10 highest-spending customers?",
        "gold_sql": """
            SELECT ROUND(100.0 * (SELECT SUM(tot) FROM (SELECT SUM(Total) tot FROM Invoice GROUP BY CustomerId ORDER BY tot DESC LIMIT 10)) / (SELECT SUM(Total) FROM Invoice), 2)
        """,
        "gold_answer": 19.38,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many customers have never purchased a Rock genre track?",
        "gold_sql": """
            SELECT COUNT(*) FROM Customer c WHERE c.CustomerId NOT IN (SELECT DISTINCT i.CustomerId FROM Invoice i JOIN InvoiceLine il ON i.InvoiceId=il.InvoiceId JOIN Track t ON il.TrackId=t.TrackId JOIN Genre g ON t.GenreId=g.GenreId WHERE g.Name='Rock')
        """,
        "gold_answer": 0,
        "type": "fact",
    },
    {
        "question": "Which media type generates the most revenue?",
        "gold_sql": """
            SELECT mt.Name, ROUND(SUM(il.UnitPrice*il.Quantity),2) rev FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId JOIN MediaType mt ON t.MediaTypeId=mt.MediaTypeId GROUP BY mt.MediaTypeId ORDER BY rev DESC LIMIT 1
        """,
        "gold_answer": [("MPEG audio file", 1956.24)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many tracks use each media type?",
        "gold_sql": """
            SELECT mt.Name, COUNT(*) FROM Track t JOIN MediaType mt ON t.MediaTypeId=mt.MediaTypeId GROUP BY mt.MediaTypeId ORDER BY mt.Name
        """,
        "gold_answer": [("AAC audio file", 11), ("MPEG audio file", 3034), ("Protected AAC audio file", 237), ("Protected MPEG-4 video file", 214), ("Purchased AAC audio file", 7)],
        "type": "fact",
    },
    {
        "question": "What is the file size, in megabytes, of the largest track in the catalog?",
        "gold_sql": "SELECT ROUND(MAX(Bytes)/1048576.0,2) FROM Track",
        "gold_answer": 1010.46,
        "type": "fact",
        "tolerance": 0.1,
    },
    {
        "question": "What is the average file size, in megabytes, of tracks in the catalog?",
        "gold_sql": "SELECT ROUND(AVG(Bytes)/1048576.0,2) FROM Track",
        "gold_answer": 31.96,
        "type": "fact",
        "tolerance": 0.1,
    },
    {
        "question": "Which genre has the largest average file size, in bytes?",
        "gold_sql": """
            SELECT g.Name, ROUND(AVG(t.Bytes),2) avgb FROM Track t JOIN Genre g ON t.GenreId=g.GenreId GROUP BY g.GenreId ORDER BY avgb DESC LIMIT 1
        """,
        "gold_answer": [("Sci Fi & Fantasy", 532930426.15)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "What is the total number of invoice line items across all invoices?",
        "gold_sql": "SELECT COUNT(*) FROM InvoiceLine",
        "gold_answer": 2240,
        "type": "fact",
    },
    {
        "question": "How many invoice line items have a quantity greater than 1?",
        "gold_sql": "SELECT COUNT(*) FROM InvoiceLine WHERE Quantity > 1",
        "gold_answer": 0,
        "type": "fact",
    },
    {
        "question": "Which track appears in the most playlists?",
        "gold_sql": """
            SELECT t.Name, COUNT(*) c FROM PlaylistTrack pt JOIN Track t ON pt.TrackId=t.TrackId GROUP BY t.TrackId ORDER BY c DESC, t.Name LIMIT 1
        """,
        "gold_answer": [("A Midsummer Night's Dream, Op.61 Incidental Music: No.7 Notturno", 5)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "How many tracks appear in more than 5 playlists?",
        "gold_sql": """
            SELECT COUNT(*) FROM (SELECT TrackId FROM PlaylistTrack GROUP BY TrackId HAVING COUNT(*) > 5)
        """,
        "gold_answer": 0,
        "type": "fact",
    },
    {
        "question": "How many albums does the artist Iron Maiden have in the catalog?",
        "gold_sql": """
            SELECT COUNT(*) FROM Album al JOIN Artist ar ON al.ArtistId=ar.ArtistId WHERE ar.Name='Iron Maiden'
        """,
        "gold_answer": 21,
        "type": "fact",
    },
    {
        "question": "What is the total revenue generated by tracks composed by Steve Harris?",
        "gold_sql": """
            SELECT ROUND(COALESCE(SUM(il.UnitPrice*il.Quantity),0),2) FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId WHERE t.Composer='Steve Harris'
        """,
        "gold_answer": 57.42,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "How many customers are located outside the USA?",
        "gold_sql": "SELECT COUNT(*) FROM Customer WHERE Country != 'USA'",
        "gold_answer": 46,
        "type": "fact",
    },
    {
        "question": "What is the total revenue from customers located outside the USA?",
        "gold_sql": """
            SELECT ROUND(SUM(i.Total),2) FROM Invoice i JOIN Customer c ON i.CustomerId=c.CustomerId WHERE c.Country != 'USA'
        """,
        "gold_answer": 1805.54,
        "type": "fact",
        "tolerance": 0.01,
    },
    {
        "question": "Which genre has the second-highest total revenue?",
        "gold_sql": """
            SELECT g.Name, ROUND(SUM(il.UnitPrice*il.Quantity),2) rev FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId JOIN Genre g ON t.GenreId=g.GenreId GROUP BY g.GenreId ORDER BY rev DESC LIMIT 1 OFFSET 1
        """,
        "gold_answer": [("Latin", 382.14)],
        "type": "ranking",
    },
    {
        "question": "How many tracks have a price higher than the average track price?",
        "gold_sql": "SELECT COUNT(*) FROM Track WHERE UnitPrice > (SELECT AVG(UnitPrice) FROM Track)",
        "gold_answer": 213,
        "type": "fact",
    },
    {
        "question": "How many customers share a last name with an employee?",
        "gold_sql": """
            SELECT COUNT(DISTINCT c.CustomerId) FROM Customer c JOIN Employee e ON c.LastName = e.LastName
        """,
        "gold_answer": 1,
        "type": "fact",
    },
    {
        "question": "Which US state has the most customers?",
        "gold_sql": """
            SELECT State, COUNT(*) c FROM Customer WHERE Country='USA' GROUP BY State ORDER BY c DESC, State LIMIT 1
        """,
        "gold_answer": [("CA", 3)],
        "type": "ranking",
        "requested_n": 1,
    },
    {
        "question": "Compare the average invoice total between customers in the USA and customers in France.",
        "gold_sql": """
            SELECT BillingCountry, ROUND(AVG(Total),2) FROM Invoice WHERE BillingCountry IN ('USA','France') GROUP BY BillingCountry ORDER BY BillingCountry
        """,
        "gold_answer": [("France", 5.57), ("USA", 5.75)],
        "type": "comparison",
    },
]
