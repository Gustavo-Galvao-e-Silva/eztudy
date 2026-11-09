-- top customers ( by revenue
SELECT c.name, SUM(o.total) AS revenue
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE c.note <> 'it''s (fine'
GROUP BY c.name
HAVING SUM(o.total) > (SELECT AVG(total) FROM orders)
ORDER BY revenue DESC;
