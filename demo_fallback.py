"""Offline demo mode: maps a fixed set of example questions to pre-written
SQL so the app is fully demoable without an API key."""

DEMO_QUERIES = {
    "top 5 artists by revenue": """
        SELECT ar.Name AS Artist, ROUND(SUM(il.UnitPrice * il.Quantity), 2) AS Revenue
        FROM InvoiceLine il
        JOIN Track t ON il.TrackId = t.TrackId
        JOIN Album al ON t.AlbumId = al.AlbumId
        JOIN Artist ar ON al.ArtistId = ar.ArtistId
        GROUP BY ar.Name
        ORDER BY Revenue DESC
        LIMIT 5;
    """,
    "which country has the most customers": """
        SELECT Country, COUNT(*) AS CustomerCount
        FROM Customer
        GROUP BY Country
        ORDER BY CustomerCount DESC
        LIMIT 100;
    """,
    "total revenue by genre": """
        SELECT g.Name AS Genre, ROUND(SUM(il.UnitPrice * il.Quantity), 2) AS Revenue
        FROM InvoiceLine il
        JOIN Track t ON il.TrackId = t.TrackId
        JOIN Genre g ON t.GenreId = g.GenreId
        GROUP BY g.Name
        ORDER BY Revenue DESC
        LIMIT 100;
    """,
    "who are the top 10 customers by total spend": """
        SELECT c.FirstName || ' ' || c.LastName AS Customer, ROUND(SUM(i.Total), 2) AS TotalSpend
        FROM Invoice i
        JOIN Customer c ON i.CustomerId = c.CustomerId
        GROUP BY c.CustomerId
        ORDER BY TotalSpend DESC
        LIMIT 10;
    """,
    "monthly revenue trend": """
        SELECT strftime('%Y-%m', InvoiceDate) AS Month, ROUND(SUM(Total), 2) AS Revenue
        FROM Invoice
        GROUP BY Month
        ORDER BY Month
        LIMIT 100;
    """,
}


def match_demo_query(question: str):
    """Very simple keyword match against the fixed demo set. Real questions
    go through the LLM in live mode; this only covers the example buttons."""
    q = question.strip().lower()
    for key, sql in DEMO_QUERIES.items():
        if q == key or q in key or key in q:
            return sql.strip()
    return None
